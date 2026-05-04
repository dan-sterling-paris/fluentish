import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from app import clicksend, crud
from app.config import settings
from app.database import AsyncSessionLocal, get_db, init_db
from app.models import LeadStatus
from app.scheduler import start_scheduler, stop_scheduler
from app.schemas import LeadOut, MessageOut, SendMessageIn
from app.sheets import _normalize_phone


class StatusUpdateIn(BaseModel):
    status: LeadStatus

logger = logging.getLogger(__name__)

# ── SSE broadcast ────────────────────────────────────────────────────────────

_sse_queues: set[asyncio.Queue] = set()


async def broadcast_event(lead_id: int, event_type: str, data: dict) -> None:
    payload = json.dumps({"lead_id": lead_id, "type": event_type, **data})
    for q in list(_sse_queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


# ── App lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    await init_db()
    start_scheduler(AsyncSessionLocal)
    yield
    stop_scheduler()


app = FastAPI(title="FluentISH CRM", lifespan=lifespan)

_base_dir = Path(__file__).parent
templates = Jinja2Templates(directory=str(_base_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(_base_dir.parent / "static")), name="static")


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    leads = await crud.get_all_leads(db)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "leads": leads,
            "template_2": settings.template_2,
            "template_3": settings.template_3,
        },
    )


@app.get("/api/leads", response_model=list[LeadOut])
async def list_leads(status: str | None = None, db: AsyncSession = Depends(get_db)):
    return await crud.get_all_leads(db, status=status)


@app.get("/api/leads/{lead_id}/messages", response_model=list[MessageOut])
async def get_messages(lead_id: int, db: AsyncSession = Depends(get_db)):
    lead = await crud.get_lead_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return await crud.get_messages_for_lead(db, lead_id)


@app.post("/api/leads/{lead_id}/send")
async def send_message(
    lead_id: int,
    body_in: SendMessageIn,
    db: AsyncSession = Depends(get_db),
):
    lead = await crud.get_lead_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not body_in.body.strip():
        raise HTTPException(status_code=400, detail="Message body cannot be empty")

    await clicksend.send_sms(lead.phone, body_in.body)
    msg = await crud.create_message(db, lead_id, "outbound", body_in.body)
    msg_data = MessageOut.model_validate(msg).model_dump(mode="json")
    await broadcast_event(lead_id, "new_message", msg_data)
    return {"ok": True}


@app.post("/api/leads/{lead_id}/template/{n}")
async def send_template(
    lead_id: int,
    n: int,
    db: AsyncSession = Depends(get_db),
):
    lead = await crud.get_lead_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    tmpl = {2: settings.template_2, 3: settings.template_3}.get(n)
    if not tmpl:
        raise HTTPException(status_code=400, detail="Invalid template number (use 2 or 3)")

    body = tmpl.replace("{name}", lead.name)
    await clicksend.send_sms(lead.phone, body)
    msg = await crud.create_message(db, lead_id, "outbound", body)

    # Update status only if not already at a more advanced state
    if lead.status == LeadStatus.new:
        await crud.update_lead_status(db, lead, LeadStatus.auto_contacted)

    msg_data = MessageOut.model_validate(msg).model_dump(mode="json")
    await broadcast_event(lead_id, "new_message", msg_data)
    # Also broadcast a status update so the sidebar refreshes
    await broadcast_event(lead_id, "status_update", {"status": lead.status.value})
    return {"ok": True}


@app.patch("/api/leads/{lead_id}/status")
async def patch_lead_status(
    lead_id: int,
    body: StatusUpdateIn,
    db: AsyncSession = Depends(get_db),
):
    lead = await crud.get_lead_by_id(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await crud.update_lead_status(db, lead, body.status)
    await broadcast_event(lead_id, "status_update", {"status": body.status.value})
    return {"ok": True}


@app.post("/webhook/inbound")
async def inbound_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    if settings.clicksend_webhook_secret:
        secret = request.query_params.get("secret", "")
        if secret != settings.clicksend_webhook_secret:
            raise HTTPException(status_code=403, detail="Forbidden")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    for msg_data in payload.get("messages", []):
        from_phone = _normalize_phone(msg_data.get("from", ""))
        body = msg_data.get("body", "").strip()

        if not from_phone or not body:
            continue

        lead = await crud.get_lead_by_phone(db, from_phone)
        if not lead:
            # Unknown sender — create stub lead using phone as name
            try:
                lead = await crud.create_lead(db, name=from_phone, phone=from_phone)
            except Exception:
                logger.exception("Failed to create stub lead for %s", from_phone)
                continue

        await crud.update_lead_status(db, lead, LeadStatus.replied)
        msg = await crud.create_message(db, lead.id, "inbound", body)
        msg_out = MessageOut.model_validate(msg).model_dump(mode="json")
        await broadcast_event(lead.id, "new_message", msg_out)
        await broadcast_event(lead.id, "status_update", {"status": LeadStatus.replied.value})

    return {"ok": True}


@app.get("/events")
async def sse_stream(request: Request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_queues.add(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _sse_queues.discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
