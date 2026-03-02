"""Stock screener API endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sql_delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import ScreenResult, User
from app.db.session import get_db

router = APIRouter(prefix="/v1/screener", tags=["screener"])


@router.get("/results")
async def list_screen_results(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all screen results for the current user."""
    result = await db.execute(
        select(ScreenResult)
        .where(ScreenResult.user_id == user.id)
        .order_by(desc(ScreenResult.created_at))
        .limit(50)
    )
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "screen_name": r.screen_name,
            "params": r.params,
            "summary": {
                "total_screened": r.summary.get("total_screened"),
                "matches_found": r.summary.get("matches_found"),
            },
            "created_at": r.created_at.isoformat(),
            "job_id": str(r.job_id) if r.job_id else None,
        }
        for r in rows
    ]


@router.get("/results/{result_id}")
async def get_screen_result(
    result_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full screen result including matches and common features."""
    result = await db.execute(
        select(ScreenResult).where(
            ScreenResult.id == result_id,
            ScreenResult.user_id == user.id,
        )
    )
    screen = result.scalar_one_or_none()
    if screen is None:
        raise HTTPException(status_code=404, detail="Screen result not found")

    return {
        "id": str(screen.id),
        "screen_name": screen.screen_name,
        "screen_version": screen.screen_version,
        "params": screen.params,
        "summary": screen.summary,
        "matches": screen.matches,
        "artefact_ids": screen.artefact_ids,
        "created_at": screen.created_at.isoformat(),
        "job_id": str(screen.job_id) if screen.job_id else None,
    }


@router.delete("/results/{result_id}", status_code=204)
async def delete_screen_result(
    result_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a screen result."""
    result = await db.execute(
        select(ScreenResult).where(
            ScreenResult.id == result_id,
            ScreenResult.user_id == user.id,
        )
    )
    screen = result.scalar_one_or_none()
    if screen is None:
        raise HTTPException(status_code=404, detail="Screen result not found")

    await db.delete(screen)
    await db.commit()
