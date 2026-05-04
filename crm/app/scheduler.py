import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.sheets import poll_and_ingest

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler(db_session_factory) -> None:
    scheduler.add_job(
        poll_and_ingest,
        trigger=IntervalTrigger(seconds=15),
        args=[db_session_factory],
        id="sheets_poll",
        replace_existing=True,
        misfire_grace_time=10,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started — polling Google Sheets every 15 seconds")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
