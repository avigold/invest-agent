"""Signal change alerts API."""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import SignalChange, User
from app.db.session import get_db

router = APIRouter(prefix="/v1/signals", tags=["signals"])


@router.get("/changes")
async def list_signal_changes(
    limit: int = Query(20, ge=1, le=100),
    system: str | None = Query(None, description="Filter: deterministic or ml"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return recent signal classification changes."""
    q = select(SignalChange).order_by(desc(SignalChange.detected_at))

    if system:
        q = q.where(SignalChange.system == system)

    q = q.limit(limit)

    result = await db.execute(q)
    rows = result.scalars().all()

    return [
        {
            "id": str(r.id),
            "ticker": r.ticker,
            "company_name": r.company_name,
            "system": r.system,
            "old_classification": r.old_classification,
            "new_classification": r.new_classification,
            "old_score": r.old_score,
            "new_score": r.new_score,
            "detected_at": r.detected_at.isoformat(),
        }
        for r in rows
    ]
