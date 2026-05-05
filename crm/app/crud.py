from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lead, LeadStatus, Message


async def get_all_leads(db: AsyncSession, status: str | None = None) -> list[dict]:
    last_msg_sq = (
        select(func.max(Message.sent_at))
        .where(Message.lead_id == Lead.id)
        .correlate(Lead)
        .scalar_subquery()
    )
    stmt = select(Lead, last_msg_sq.label("last_message_at"))
    if status and status != "all":
        stmt = stmt.where(Lead.status == status)
    stmt = stmt.order_by(Lead.updated_at.desc())
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": lead.id,
            "name": lead.name,
            "phone": lead.phone,
            "status": lead.status,
            "created_at": lead.created_at,
            "updated_at": lead.updated_at,
            "last_message_at": last_message_at,
        }
        for lead, last_message_at in rows
    ]


async def get_lead_by_id(db: AsyncSession, lead_id: int) -> Lead | None:
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    return result.scalar_one_or_none()


async def get_lead_by_phone(db: AsyncSession, phone: str) -> Lead | None:
    result = await db.execute(select(Lead).where(Lead.phone == phone))
    return result.scalar_one_or_none()


async def create_lead(db: AsyncSession, name: str, phone: str) -> Lead:
    lead = Lead(name=name, phone=phone, status=LeadStatus.new)
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


async def update_lead_status(db: AsyncSession, lead: Lead, status: LeadStatus) -> Lead:
    lead.status = status
    lead.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(lead)
    return lead


async def create_message(
    db: AsyncSession, lead_id: int, direction: str, body: str
) -> Message:
    msg = Message(lead_id=lead_id, direction=direction, body=body)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def get_messages_for_lead(db: AsyncSession, lead_id: int) -> list[Message]:
    result = await db.execute(
        select(Message).where(Message.lead_id == lead_id).order_by(Message.sent_at.asc())
    )
    return list(result.scalars().all())
