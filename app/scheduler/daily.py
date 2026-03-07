"""Scheduler — automated data sync, scoring, and company discovery.

Uses APScheduler to run data ingestion and scoring jobs on a schedule.
Enabled via SCHEDULER_ENABLED=true environment variable.

Schedule (UTC):
  Every 4h  — price_sync (stock prices for all companies + indices)
  06:00     — macro_sync scope=daily (FRED + country market data)
  Sun 04:00 — fmp_sync (FMP fundamentals for all companies)
  Sun 06:00 — score_sync (re-score stale companies)
  1st 02:00 — discover_companies (find newly listed companies)
  1st 03:00 — macro_sync scope=monthly (WB, IMF, FRED, GDELT, market)
  1st 07:00 — country_refresh + industry_refresh (rescore)
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
    """APScheduler-based scheduler for automated data sync and scoring."""

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

        # Every 4 hours — stock prices for all companies + country indices
        self._scheduler.add_job(
            self._run_price_sync,
            "cron",
            hour="0,4,8,12,16,20",
            minute=0,
            id="price_sync",
            replace_existing=True,
        )

        # Daily 06:00 — FRED + country market data (fast)
        self._scheduler.add_job(
            self._run_daily_macro,
            "cron",
            hour=6,
            minute=0,
            id="daily_macro_sync",
            replace_existing=True,
        )

        # Weekly Sunday 04:00 — FMP fundamentals for all companies
        self._scheduler.add_job(
            self._run_fmp_sync,
            "cron",
            day_of_week="sun",
            hour=4,
            minute=0,
            id="weekly_fmp_sync",
            replace_existing=True,
        )

        # Weekly Sunday 06:00 — re-score all stale companies
        self._scheduler.add_job(
            self._run_score_sync,
            "cron",
            day_of_week="sun",
            hour=6,
            minute=0,
            id="weekly_score_sync",
            replace_existing=True,
        )

        # Monthly 1st 02:00 — discover newly listed companies
        self._scheduler.add_job(
            self._run_discover_companies,
            "cron",
            day=1,
            hour=2,
            minute=0,
            id="monthly_discover",
            replace_existing=True,
        )

        # Monthly 1st 03:00 — slow macro data (WB, IMF, GDELT)
        self._scheduler.add_job(
            self._run_monthly_macro,
            "cron",
            day=1,
            hour=3,
            minute=0,
            id="monthly_macro_sync",
            replace_existing=True,
        )

        # Monthly 1st 07:00 — rescore countries + industries
        self._scheduler.add_job(
            self._run_rescore,
            "cron",
            day=1,
            hour=7,
            minute=0,
            id="monthly_rescore",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info("Scheduler started (timezone=%s, 7 jobs)", tz)

    async def stop(self) -> None:
        """Shut down the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    # --- Job launchers ---

    async def _run_price_sync(self) -> None:
        async with self._session_factory() as db:
            await _ensure_system_user(db)
        _enqueue_job(
            self._registry, self._job_queue, self._run_fn,
            "price_sync", {},
        )

    async def _run_daily_macro(self) -> None:
        async with self._session_factory() as db:
            await _ensure_system_user(db)
        _enqueue_job(
            self._registry, self._job_queue, self._run_fn,
            "macro_sync", {"scope": "daily"},
        )

    async def _run_fmp_sync(self) -> None:
        async with self._session_factory() as db:
            await _ensure_system_user(db)
        _enqueue_job(
            self._registry, self._job_queue, self._run_fn,
            "fmp_sync", {"concurrency": 10},
        )

    async def _run_score_sync(self) -> None:
        async with self._session_factory() as db:
            await _ensure_system_user(db)
        _enqueue_job(
            self._registry, self._job_queue, self._run_fn,
            "score_sync", {},
        )

    async def _run_discover_companies(self) -> None:
        async with self._session_factory() as db:
            await _ensure_system_user(db)
        _enqueue_job(
            self._registry, self._job_queue, self._run_fn,
            "discover_companies", {},
        )

    async def _run_monthly_macro(self) -> None:
        async with self._session_factory() as db:
            await _ensure_system_user(db)
        _enqueue_job(
            self._registry, self._job_queue, self._run_fn,
            "macro_sync", {"scope": "monthly"},
        )

    async def _run_rescore(self) -> None:
        async with self._session_factory() as db:
            await _ensure_system_user(db)
        for command in ("country_refresh", "industry_refresh"):
            _enqueue_job(
                self._registry, self._job_queue, self._run_fn,
                command, {},
            )
