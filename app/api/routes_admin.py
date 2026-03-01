"""Admin panel API endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.models import Job, Subscription, User
from app.db.session import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


class SetRoleRequest(BaseModel):
    role: str


VALID_ROLES = {"user", "admin"}


@router.get("/stats")
async def admin_stats(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate stats for the admin dashboard."""
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0

    pro_subs = (
        await db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.plan == "pro",
                Subscription.status.in_(["active", "trialing"]),
            )
        )
    ).scalar() or 0

    today = datetime.now(tz=timezone.utc).date()
    jobs_today = (
        await db.execute(
            select(func.count(Job.id)).where(
                func.date(Job.queued_at) == today,
            )
        )
    ).scalar() or 0

    running = (
        await db.execute(
            select(func.count(Job.id)).where(Job.status == "running")
        )
    ).scalar() or 0

    queued = (
        await db.execute(
            select(func.count(Job.id)).where(Job.status == "queued")
        )
    ).scalar() or 0

    return {
        "total_users": total_users,
        "pro_subscribers": pro_subs,
        "jobs_today": jobs_today,
        "running": running,
        "queued": queued,
    }


@router.get("/users")
async def admin_list_users(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users with stats."""
    result = await db.execute(
        select(
            User.id,
            User.email,
            User.name,
            User.role,
            User.plan,
            User.created_at,
            func.count(Job.id).label("job_count"),
            func.max(Job.queued_at).label("last_active"),
        )
        .outerjoin(Job, Job.user_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at.desc())
    )

    # Also load subscription info
    sub_result = await db.execute(
        select(Subscription.user_id, Subscription.plan, Subscription.status)
    )
    sub_map = {row.user_id: {"plan": row.plan, "status": row.status} for row in sub_result}

    users = []
    for row in result:
        sub = sub_map.get(row.id, {})
        # Effective plan: admins always get pro
        effective = "pro" if row.role == "admin" else sub.get("plan", row.plan)
        users.append({
            "id": str(row.id),
            "email": row.email,
            "name": row.name,
            "role": row.role,
            "plan": effective,
            "sub_plan": sub.get("plan", "free"),
            "sub_status": sub.get("status"),
            "job_count": row.job_count,
            "last_active": row.last_active.isoformat() if row.last_active else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return users


@router.get("/jobs")
async def admin_list_jobs(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List last 200 jobs across all users."""
    result = await db.execute(
        select(Job, User.email, User.name)
        .outerjoin(User, Job.user_id == User.id)
        .order_by(Job.queued_at.desc())
        .limit(200)
    )

    jobs = []
    for job, email, name in result:
        jobs.append({
            "id": str(job.id),
            "command": job.command,
            "status": job.status,
            "params": job.params,
            "user_email": email,
            "user_name": name,
            "queued_at": job.queued_at.isoformat() if job.queued_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        })

    return jobs


@router.post("/users/{user_id}/role")
async def admin_set_role(
    user_id: str,
    body: SetRoleRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {sorted(VALID_ROLES)}")

    result = await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(role=body.role)
        .returning(User.id, User.role)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    await db.commit()
    return {"status": "ok", "user_id": str(row.id), "role": row.role}
