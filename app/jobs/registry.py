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

from sqlalchemy import select
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
    artefact_ids: list[str] | None = None
    packet_id: str | None = None

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
        self._active_ids: set[uuid.UUID] = set()  # jobs created in this server lifetime

    async def load_existing(self, db: AsyncSession) -> None:
        """Load recent jobs from DB for display.

        Jobs stuck in 'running' or 'queued' from a previous server lifetime
        cannot actually be running — mark them 'failed' in the DB so they
        don't show misleading status.
        """
        from sqlalchemy import update
        await db.execute(
            update(JobModel)
            .where(JobModel.status.in_(["running", "queued"]))
            .values(status="failed", finished_at=_utcnow())
        )
        await db.commit()

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
            self._active_ids.add(job.id)
        return job

    def get(self, job_id: uuid.UUID) -> LiveJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_for_user(self, user_id: uuid.UUID) -> list[LiveJob]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.user_id == user_id]
        return sorted(jobs, key=lambda j: j.queued_at, reverse=True)

    def has_running_job(self, user_id: uuid.UUID) -> bool:
        """Return True if the user has an active running or queued job.

        Only considers jobs created in this server lifetime — stale jobs
        from a previous process cannot actually be running.
        """
        with self._lock:
            return any(
                j.id in self._active_ids
                and j.user_id == user_id
                and j.status in ("running", "queued")
                for j in self._jobs.values()
            )

    def delete(self, job_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Remove a finished job from memory. Returns True if found and deleted."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.user_id != user_id:
                return False
            if job.status in ("running", "queued"):
                return False  # must cancel first
            del self._jobs[job_id]
            self._active_ids.discard(job_id)
        return True

    async def delete_from_db(self, job_id: uuid.UUID, db: AsyncSession) -> None:
        """Delete a job row from Postgres."""
        from sqlalchemy import delete as sql_delete
        await db.execute(sql_delete(JobModel).where(JobModel.id == job_id))
        await db.commit()

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
        packet_uuid = uuid.UUID(job.packet_id) if job.packet_id else None
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
            artefact_ids=job.artefact_ids,
            packet_id=packet_uuid,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "status": stmt.excluded.status,
                "started_at": stmt.excluded.started_at,
                "finished_at": stmt.excluded.finished_at,
                "log_text": stmt.excluded.log_text,
                "artefact_ids": stmt.excluded.artefact_ids,
                "packet_id": stmt.excluded.packet_id,
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
