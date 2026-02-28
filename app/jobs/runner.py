"""Job runner: executes job handlers in-process.

Unlike the chess app's subprocess-based runner, Invest Agent runs
handlers as async functions directly. Log lines are pushed to the
LiveJob's queue for SSE streaming.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


async def run_job(
    job: LiveJob,
    registry: JobRegistry,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Execute a job handler, streaming log lines to the LiveJob's queue."""
    handler = get_handler(job.command)

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


def make_run_fn(registry: JobRegistry, session_factory: async_sessionmaker[AsyncSession]):
    """Create a run function bound to the registry and session factory."""
    async def _run(job: LiveJob) -> None:
        await run_job(job, registry, session_factory)
    return _run
