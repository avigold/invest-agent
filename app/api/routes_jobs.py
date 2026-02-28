"""Job API routes: create, list, detail, stream, cancel.

SSE streaming pattern adapted from mysecond.app server.py:418-457.
Plan gating adapted from server.py:500-535.
"""
from __future__ import annotations

import asyncio
import json
import queue
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import effective_plan, get_current_user
from app.db.models import User
from app.db.session import get_db
from app.jobs.schemas import JobCommand, JobCreate, JobDetail, JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# These are set during app startup (see main.py lifespan).
_registry = None
_job_queue = None
_run_fn = None


def init_job_globals(registry, job_queue, run_fn):
    global _registry, _job_queue, _run_fn
    _registry = registry
    _job_queue = job_queue
    _run_fn = run_fn


# ---------------------------------------------------------------------------
# Plan gating (mirrors chess app _FREE_LIMITS + _check_plan_limit)
# ---------------------------------------------------------------------------

_FREE_LIMITS: dict[str, int] = {
    "country_refresh": 5,
    "industry_refresh": 5,
    "company_refresh": 5,
    "universe_refresh": 2,
    "backfill": 2,
}


async def _check_plan_limit(user: User, command: str, db: AsyncSession) -> None:
    plan = effective_plan(user)
    if plan == "pro":
        return
    limit = _FREE_LIMITS.get(command)
    if limit is None:
        return  # no limit for this command (e.g. echo)
    count = await _registry.count_monthly_jobs(user.id, command, db)
    if count >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "error": f"Free plan: {count}/{limit} {command} jobs used this month.",
                "upgrade_url": "/pricing",
            },
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", response_model=JobResponse)
async def create_job(
    body: JobCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue a new job."""
    # Per-user concurrency limit
    if _registry.has_running_job(user.id):
        raise HTTPException(
            status_code=409,
            detail="You already have a job running or queued. "
                   "Wait for it to finish or cancel it before starting a new one.",
        )

    # Plan limit
    await _check_plan_limit(user, body.command.value, db)

    # Create and persist
    job = _registry.create(
        command=body.command.value,
        params=body.params,
        user_id=user.id,
    )
    await _registry.persist(job, db)

    # Enqueue
    _job_queue.enqueue(job, _registry, _run_fn)

    return JobResponse(
        id=job.id,
        command=job.command,
        params=job.params,
        status=job.status,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("", response_model=list[JobResponse])
async def list_jobs(user: User = Depends(get_current_user)):
    """List all jobs for the current user."""
    jobs = _registry.list_for_user(user.id)
    return [
        JobResponse(
            id=j.id,
            command=j.command,
            params=j.params,
            status=j.status,
            queued_at=j.queued_at,
            started_at=j.started_at,
            finished_at=j.finished_at,
        )
        for j in jobs
    ]


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: uuid.UUID, user: User = Depends(get_current_user)):
    """Get job detail including log text and queue position."""
    job = _registry.get(job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobDetail(
        id=job.id,
        command=job.command,
        params=job.params,
        status=job.status,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        log_text="\n".join(job.log_lines) if job.log_lines else None,
        queue_position=_job_queue.queue_position(job.id) if job.status == "queued" else None,
    )


@router.get("/{job_id}/stream")
async def stream_job(job_id: uuid.UUID, user: User = Depends(get_current_user)):
    """SSE endpoint that streams job log lines in real time.

    Same pattern as mysecond.app: queued → return, finished → replay, running → live.
    """
    job = _registry.get(job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        # If the job is queued, tell the client to poll and wait.
        if job.status == "queued":
            yield {"event": "queued", "data": ""}
            return

        # If the job is already finished, replay stored lines then close.
        if job.status not in ("running",):
            for line in job.log_lines:
                yield {"event": "message", "data": json.dumps({"line": line})}
            yield {"event": "done", "data": ""}
            return

        # Replay lines already logged before this SSE client connected.
        for line in list(job.log_lines):
            yield {"event": "message", "data": json.dumps({"line": line})}

        # Live streaming — new lines arrive via the queue.
        while True:
            try:
                item = await asyncio.get_event_loop().run_in_executor(
                    None, job.queue.get, True, 5.0
                )
                if item is None:
                    # Sentinel: job finished.
                    yield {"event": "done", "data": ""}
                    break
                yield {"event": "message", "data": json.dumps({"line": item})}
            except queue.Empty:
                # Keepalive to prevent proxy/browser timeout.
                yield {"event": "ping", "data": ""}

    return EventSourceResponse(event_generator())


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running or queued job."""
    job = _registry.get(job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if not _registry.mark_cancelled(job_id):
        raise HTTPException(status_code=400, detail="Job cannot be cancelled")

    _job_queue.remove(job_id)
    await _registry.persist(job, db)

    return {"ok": True}


@router.delete("/{job_id}")
async def delete_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a finished/failed/cancelled job from history."""
    if not _registry.delete(job_id, user.id):
        job = _registry.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a running or queued job. Cancel it first.",
        )

    await _registry.delete_from_db(job_id, db)
    return {"ok": True}
