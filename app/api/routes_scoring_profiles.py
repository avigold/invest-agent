"""Scoring profile CRUD API endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import ScoringProfile, User
from app.db.session import get_db
from app.score.profile_schema import (
    ScoringProfileConfig,
    default_profile_config,
    merge_with_defaults,
)

router = APIRouter(prefix="/v1/scoring-profiles", tags=["scoring-profiles"])

MAX_PROFILES_PER_USER = 10


class CreateProfileRequest(BaseModel):
    name: str
    config: dict


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    config: dict | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/defaults")
async def get_defaults(user: User = Depends(get_current_user)):
    """Return system default scoring profile config."""
    return default_profile_config().model_dump()


@router.get("")
async def list_profiles(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's scoring profiles (without full config)."""
    result = await db.execute(
        select(ScoringProfile)
        .where(ScoringProfile.user_id == user.id)
        .order_by(ScoringProfile.created_at)
    )
    profiles = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "is_default": p.is_default,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in profiles
    ]


@router.post("")
async def create_profile(
    body: CreateProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new scoring profile."""
    # Check limit
    count_result = await db.execute(
        select(ScoringProfile).where(ScoringProfile.user_id == user.id)
    )
    if len(count_result.scalars().all()) >= MAX_PROFILES_PER_USER:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_PROFILES_PER_USER} profiles allowed")

    if not body.name or not body.name.strip():
        raise HTTPException(status_code=422, detail="Profile name is required")

    # Merge with defaults and validate
    merged = merge_with_defaults(body.config)
    try:
        ScoringProfileConfig(**merged)
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    profile = ScoringProfile(
        user_id=user.id,
        name=body.name.strip(),
        config=merged,
    )
    db.add(profile)
    try:
        await db.commit()
        await db.refresh(profile)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A profile with that name already exists")

    return _profile_response(profile)


@router.get("/{profile_id}")
async def get_profile(
    profile_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a scoring profile with full config."""
    profile = await _get_owned_profile(db, profile_id, user.id)
    return _profile_response(profile)


@router.put("/{profile_id}")
async def update_profile(
    profile_id: uuid.UUID,
    body: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a scoring profile's name and/or config."""
    profile = await _get_owned_profile(db, profile_id, user.id)

    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="Profile name cannot be empty")
        profile.name = body.name.strip()

    if body.config is not None:
        merged = merge_with_defaults(body.config)
        try:
            ScoringProfileConfig(**merged)
        except (ValidationError, ValueError) as e:
            raise HTTPException(status_code=422, detail=str(e))
        profile.config = merged

    try:
        await db.commit()
        await db.refresh(profile)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A profile with that name already exists")

    return _profile_response(profile)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a scoring profile."""
    profile = await _get_owned_profile(db, profile_id, user.id)
    await db.delete(profile)
    await db.commit()


@router.post("/{profile_id}/activate")
async def activate_profile(
    profile_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a profile as the user's active default."""
    profile = await _get_owned_profile(db, profile_id, user.id)

    # Deactivate all others
    await db.execute(
        update(ScoringProfile)
        .where(ScoringProfile.user_id == user.id)
        .values(is_default=False)
    )
    profile.is_default = True
    await db.commit()
    return {"status": "ok", "profile_id": str(profile.id)}


@router.post("/deactivate")
async def deactivate_profiles(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear the user's active profile (use system defaults)."""
    await db.execute(
        update(ScoringProfile)
        .where(ScoringProfile.user_id == user.id)
        .values(is_default=False)
    )
    await db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_owned_profile(
    db: AsyncSession, profile_id: uuid.UUID, user_id: uuid.UUID
) -> ScoringProfile:
    result = await db.execute(
        select(ScoringProfile).where(ScoringProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your profile")
    return profile


def _profile_response(profile: ScoringProfile) -> dict:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "is_default": profile.is_default,
        "config": profile.config,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
