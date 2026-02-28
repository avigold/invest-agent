"""Job registry: in-memory store + async PostgreSQL persistence.

Adapted from mysecond.app's JobRegistry — same thread-safe in-memory cache
pattern, but uses SQLAlchemy async instead of raw psycopg2.
"""
from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job as JobModel


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class LiveJob:
    """In-memory representation of a running or recent job."""
    id: uuid.UUID
    command: str
    params: dict
    status: str  # queued | running | done | failed | cancelled
    user_id: uuid.UUID
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    log_lines: list[str] = field(default_factory=list, repr=False)
    queue: queue.Queue = field(default_factory=queue.Queue, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "command": self.command,
            "params": self.params,
            "status": self.status,
            "user_id": str(self.user_id),
            "queued_at": self.queued_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class JobRegistry:
    """Thread-safe in-memory job cache with async Postgres persistence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[uuid.UUID, LiveJob] = {}

    async def load_existing(self, db: AsyncSession) -> None:
        """Load recent jobs from DB. Mark any 'running' as 'cancelled'."""
        # Cancel stale running jobs in DB
        await db.execute(
            update(JobModel)
            .where(JobModel.status == "running")
            .values(status="cancelled", finished_at=_utcnow())
        )
        await db.commit()

        # Load recent jobs into memory
        result = await db.execute(
            select(JobModel).order_by(JobModel.queued_at.desc()).limit(200)
        )
        rows = result.scalars().all()

        with self._lock:
            for row in rows:
                job = LiveJob(
                    id=row.id,
                    command=row.command,
                    params=row.params,
                    status=row.status,
                    user_id=row.user_id,
                    queued_at=row.queued_at,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                    log_lines=row.log_text.splitlines() if row.log_text else [],
                )
                self._jobs[row.id] = job

    def create(
        self,
        command: str,
        params: dict,
        user_id: uuid.UUID,
    ) -> LiveJob:
        """Create a new LiveJob in memory. Caller must persist to DB."""
        job = LiveJob(
            id=uuid.uuid4(),
            command=command,
            params=params,
            status="queued",
            user_id=user_id,
            queued_at=_utcnow(),
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: uuid.UUID) -> LiveJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_for_user(self, user_id: uuid.UUID) -> list[LiveJob]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.user_id == user_id]
        return sorted(jobs, key=lambda j: j.queued_at, reverse=True)

    def has_running_job(self, user_id: uuid.UUID) -> bool:
        """Return True if the user has a running or queued job."""
        with self._lock:
            return any(
                j.user_id == user_id and j.status in ("running", "queued")
                for j in self._jobs.values()
            )

    def mark_cancelled(self, job_id: uuid.UUID) -> bool:
        """Mark a running or queued job as cancelled. Returns True if found."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in ("running", "queued"):
                return False
            job.status = "cancelled"
            job.finished_at = _utcnow()
            job.queue.put(None)  # signal SSE to close
        return True

    async def persist(self, job: LiveJob, db: AsyncSession) -> None:
        """Upsert job state to Postgres."""
        stmt = pg_insert(JobModel).values(
            id=job.id,
            user_id=job.user_id,
            command=job.command,
            params=job.params,
            status=job.status,
            queued_at=job.queued_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            log_text="\n".join(job.log_lines) if job.log_lines else None,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "status": stmt.excluded.status,
                "started_at": stmt.excluded.started_at,
                "finished_at": stmt.excluded.finished_at,
                "log_text": stmt.excluded.log_text,
            },
        )
        await db.execute(stmt)
        await db.commit()

    async def count_monthly_jobs(
        self, user_id: uuid.UUID, command: str, db: AsyncSession
    ) -> int:
        """Count completed jobs for this user/command in the current month."""
        from sqlalchemy import func
        result = await db.execute(
            select(func.count())
            .select_from(JobModel)
            .where(
                JobModel.user_id == user_id,
                JobModel.command == command,
                JobModel.status == "done",
                JobModel.queued_at >= func.date_trunc("month", func.now()),
            )
        )
        return result.scalar_one()
