import asyncio
import logging
import re

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials
from sqlalchemy.exc import IntegrityError

from app.config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _build_service():
    creds = Credentials.from_service_account_file(
        settings.google_service_account_json,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _normalize_phone(raw: str) -> str:
    """Normalize to E.164 format. Handles UK numbers (07xxx → +447xxx)."""
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    elif digits.startswith("07") and len(digits) == 11:
        digits = "+44" + digits[1:]
    elif digits.startswith("7") and len(digits) == 10:
        digits = "+44" + digits
    elif not digits.startswith("+"):
        digits = "+" + digits
    return digits


def _fetch_sheet_rows() -> list[list[str]]:
    """Synchronous. Returns all data rows from A2:C (skips header row 1)."""
    service = _build_service()
    range_name = f"{settings.sheet_name}!A2:C"
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=settings.spreadsheet_id, range=range_name)
        .execute()
    )
    return result.get("values", [])


def _write_ingested_marker(row_index: int) -> None:
    """Synchronous. Writes INGESTED_MARKER to the status column for a given row."""
    service = _build_service()
    col_letter = chr(ord("A") + settings.sheet_status_col - 1)
    cell_range = f"{settings.sheet_name}!{col_letter}{row_index}"
    service.spreadsheets().values().update(
        spreadsheetId=settings.spreadsheet_id,
        range=cell_range,
        valueInputOption="RAW",
        body={"values": [[settings.ingested_marker]]},
    ).execute()


async def poll_and_ingest(db_session_factory) -> None:
    """
    Called every 15 seconds by APScheduler.
    Catches all exceptions so the poller never crashes.
    """
    if not settings.google_service_account_json or not settings.spreadsheet_id:
        logger.debug("Sheets polling skipped: credentials not configured")
        return

    try:
        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(None, _fetch_sheet_rows)
        for i, row in enumerate(rows):
            try:
                await _process_row(db_session_factory, row, row_index=i + 2)
            except Exception:
                logger.exception("Error processing sheet row %d", i + 2)
    except HttpError as exc:
        logger.error("Google Sheets API error: %s", exc)
    except Exception:
        logger.exception("Unexpected error in sheet poller")


async def _process_row(db_session_factory, row: list, row_index: int) -> None:
    if len(row) < 2:
        return

    name = row[0].strip()
    raw_phone = row[1].strip()
    status_col = row[2].strip() if len(row) > 2 else ""

    if not name or not raw_phone:
        return

    if status_col == settings.ingested_marker:
        return

    phone = _normalize_phone(raw_phone)

    # Dedup layer 2: check DB before inserting
    async with db_session_factory() as db:
        from app import crud
        existing = await crud.get_lead_by_phone(db, phone)
        if existing:
            # DB has it but sheet wasn't marked — write back the marker
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, _write_ingested_marker, row_index)
            except Exception:
                logger.exception("Failed to write catch-up marker for row %d", row_index)
            return

        try:
            lead = await crud.create_lead(db, name=name, phone=phone)
        except IntegrityError:
            await db.rollback()
            logger.warning("Race condition on phone %s, skipping", phone)
            return

        await crud.update_lead_status(db, lead, crud.LeadStatus.auto_contacted)
        lead_id = lead.id

    # Send SMS outside the DB session
    body = settings.template_1.replace("{name}", name)
    try:
        from app import clicksend
        await clicksend.send_sms(phone=phone, body=body)
        async with db_session_factory() as db:
            from app import crud
            await crud.create_message(db, lead_id, "outbound", body)
    except Exception:
        logger.exception("SMS send failed for lead %s (%s)", name, phone)

    # Always try to mark sheet ingested, even if SMS failed
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _write_ingested_marker, row_index)
    except Exception:
        logger.exception("Sheet write-back failed for row %d", row_index)
