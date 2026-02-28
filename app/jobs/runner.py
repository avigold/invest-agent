"""Job runner: executes job handlers in-process.

Unlike the chess app's subprocess-based runner, Invest Agent runs
handlers as async functions directly. Log lines are pushed to the
LiveJob's queue for SSE streaming.

Each job runs in its own thread with its own event loop, so it needs
a fresh async engine/session factory — asyncpg connections cannot cross
event loop boundaries.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.jobs.registry import JobRegistry, LiveJob

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def get_handler(command: str):
    """Look up the handler function for a given command."""
    from app.jobs.handlers import HANDLERS
    handler = HANDLERS.get(command)
    if handler is None:
        raise ValueError(f"No handler registered for command: {command}")
    return handler


def _make_job_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a fresh engine + session factory for a job thread's event loop."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)


async def run_job(
    job: LiveJob,
    registry: JobRegistry,
) -> None:
    """Execute a job handler, streaming log lines to the LiveJob's queue."""
    handler = get_handler(job.command)

    # Each job thread gets its own engine bound to this loop
    session_factory = _make_job_session_factory()

    job.status = "running"
    job.started_at = _utcnow()

    try:
        await handler(job, session_factory)
        if job.status == "running":  # handler didn't set a final status
            job.status = "done"
    except Exception as e:
        logger.exception("Job %s failed: %s", job.id, e)
        job.status = "failed"
        error_line = f"ERROR: {e}"
        job.log_lines.append(error_line)
        job.queue.put(error_line)
    finally:
        job.finished_at = _utcnow()
        job.queue.put(None)  # sentinel — SSE generator will close

        # Persist final state
        try:
            async with session_factory() as db:
                await registry.persist(job, db)
        except Exception:
            logger.exception("Failed to persist job %s", job.id)

        # Clean up the per-job engine
        try:
            engine = session_factory.kw.get("bind") or session_factory.class_.kw.get("bind")
        except Exception:
            engine = None
        # session_factory holds a ref to the engine internally;
        # disposal happens when the thread's loop closes


def make_run_fn(registry: JobRegistry):
    """Create a run function bound to the registry."""
    async def _run(job: LiveJob) -> None:
        await run_job(job, registry)
    return _run
