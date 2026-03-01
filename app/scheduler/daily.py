"""Daily scheduler — automated data sync and scoring.

Uses APScheduler to run data ingestion and scoring jobs on a schedule.
Enabled via SCHEDULER_ENABLED=true environment variable.

Schedule (UTC):
  06:00 — data_sync (all countries + companies, freshness-aware)
  07:00 — country_refresh + industry_refresh + company_refresh (rescore)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User

logger = logging.getLogger(__name__)

# Well-known UUID for the scheduler's system user.
SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _ensure_system_user(db: AsyncSession) -> uuid.UUID:
    """Ensure a system user exists for scheduler-created jobs."""
    result = await db.execute(select(User).where(User.id == SYSTEM_USER_ID))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            id=SYSTEM_USER_ID,
            email="system@investagent.app",
            name="System Scheduler",
            role="admin",
        )
        db.add(user)
        await db.commit()
    return SYSTEM_USER_ID


def _enqueue_job(registry, job_queue, run_fn, command: str, params: dict) -> None:
    """Create and enqueue a scheduled job."""
    job = registry.create(command=command, params=params, user_id=SYSTEM_USER_ID)
    job_queue.enqueue(job, registry, run_fn)
    logger.info("Scheduler enqueued %s (job %s)", command, job.id)


class DailyScheduler:
    """APScheduler-based daily scheduler for automated data sync and scoring."""

    def __init__(self, registry, job_queue, run_fn, session_factory) -> None:
        self._registry = registry
        self._job_queue = job_queue
        self._run_fn = run_fn
        self._session_factory = session_factory
        self._scheduler: AsyncIOScheduler | None = None

    async def start(self) -> None:
        """Start the scheduler if enabled."""
        settings = get_settings()
        if not settings.scheduler_enabled:
            logger.info("Scheduler disabled (SCHEDULER_ENABLED not set)")
            return

        # Ensure system user exists
        async with self._session_factory() as db:
            await _ensure_system_user(db)

        tz = settings.scheduler_timezone

        self._scheduler = AsyncIOScheduler(timezone=tz)

        # 06:00 UTC — data sync (freshness-aware ingestion only)
        self._scheduler.add_job(
            self._run_data_sync,
            "cron",
            hour=6,
            minute=0,
            id="daily_data_sync",
            replace_existing=True,
        )

        # 07:00 UTC — rescore everything
        self._scheduler.add_job(
            self._run_scoring,
            "cron",
            hour=7,
            minute=0,
            id="daily_scoring",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info("Daily scheduler started (timezone=%s)", tz)

    async def stop(self) -> None:
        """Shut down the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            logger.info("Daily scheduler stopped")

    async def _run_data_sync(self) -> None:
        """Enqueue a data_sync job."""
        # Persist the job to DB before enqueue
        async with self._session_factory() as db:
            await _ensure_system_user(db)

        _enqueue_job(
            self._registry, self._job_queue, self._run_fn,
            "data_sync", {},
        )

    async def _run_scoring(self) -> None:
        """Enqueue country, industry, and company refresh jobs (scoring only)."""
        async with self._session_factory() as db:
            await _ensure_system_user(db)

        for command in ("country_refresh", "industry_refresh", "company_refresh"):
            _enqueue_job(
                self._registry, self._job_queue, self._run_fn,
                command, {},
            )
