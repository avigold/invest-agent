"""Job queue: semaphore-based concurrency limiter.

Adapted from mysecond.app's JobQueue — same semaphore pattern,
but jobs are async handlers instead of subprocesses.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.jobs.registry import JobRegistry, LiveJob

logger = logging.getLogger(__name__)

HEAVY_COMMANDS = {
    "country_refresh", "industry_refresh", "company_refresh",
    "universe_refresh", "backfill",
}


class JobQueue:
    """Limits concurrent heavy jobs. Light jobs bypass the queue entirely."""

    def __init__(self, max_concurrent: int = 4) -> None:
        self._sem = threading.Semaphore(max_concurrent)
        self._lock = threading.Lock()
        self._waiting: list[uuid.UUID] = []  # FIFO queue of job IDs

    def enqueue(
        self,
        job: LiveJob,
        registry: JobRegistry,
        run_fn: Callable,
    ) -> None:
        """Submit a job. Launches immediately if a slot is free, else queues it."""
        if job.command not in HEAVY_COMMANDS:
            # Light jobs bypass the queue
            self._start(job, registry, run_fn)
            return

        acquired = self._sem.acquire(blocking=False)
        if acquired:
            self._start(job, registry, run_fn)
        else:
            with self._lock:
                self._waiting.append(job.id)
            with registry._lock:
                job.status = "queued"

    def queue_position(self, job_id: uuid.UUID) -> int | None:
        """Return 1-based queue position, or None if not queued."""
        with self._lock:
            try:
                return self._waiting.index(job_id) + 1
            except ValueError:
                return None

    def _start(
        self,
        job: LiveJob,
        registry: JobRegistry,
        run_fn: Callable,
    ) -> None:
        """Mark job running and launch it in a thread."""

        def _wrapper() -> None:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(run_fn(job))
            except Exception:
                logger.exception("Job %s failed", job.id)
            finally:
                loop.close()
                if job.command in HEAVY_COMMANDS:
                    self._sem.release()
                    self._promote_next(registry, run_fn)

        threading.Thread(target=_wrapper, daemon=True).start()

    def _promote_next(self, registry: JobRegistry, run_fn: Callable) -> None:
        """Start the next queued job if one exists."""
        with self._lock:
            if not self._waiting:
                return
            next_id = self._waiting.pop(0)

        with registry._lock:
            job = registry._jobs.get(next_id)
        if job is None or job.status == "cancelled":
            self._sem.release()
            self._promote_next(registry, run_fn)
            return

        if self._sem.acquire(blocking=False):
            self._start(job, registry, run_fn)

    def remove(self, job_id: uuid.UUID) -> None:
        """Remove a cancelled job from the wait list."""
        with self._lock:
            try:
                self._waiting.remove(job_id)
            except ValueError:
                pass
