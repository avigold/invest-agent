"""Google OAuth (OIDC) authentication with JWT sessions.

Adapted from mysecond.app auth.py — uses httpx (async) instead of requests,
JWT cookies instead of Flask sessions.
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory state store for OAuth flow (state -> {timestamp}).
# Entries expire after 10 minutes.
_oauth_states: dict[str, float] = {}
_STATE_TTL = 600  # seconds


def _cleanup_states() -> None:
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if now - v > _STATE_TTL]
    for k in expired:
        del _oauth_states[k]


def _create_jwt(user_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(tz=timezone.utc) + timedelta(hours=settings.jwt_expiry_hours)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@router.get("/google")
async def google_login():
    """Redirect to Google OAuth consent screen."""
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    state = secrets.token_urlsafe(16)
    _cleanup_states()
    _oauth_states[state] = time.time()

    params = {
        "response_type": "code",
        "client_id": settings.google_client_id,
        "redirect_uri": f"{settings.app_url}/auth/google/callback",
        "scope": "openid email profile",
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    return {"url": url}


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Exchange authorization code for tokens, upsert user, issue JWT."""
    settings = get_settings()

    # Verify state
    stored_time = _oauth_states.pop(state, None)
    if stored_time is None or time.time() - stored_time > _STATE_TTL:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": f"{settings.app_url}/auth/google/callback",
            },
            timeout=10,
        )
        if not token_resp.is_success:
            raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="No access token in response")

        # Fetch user info
        userinfo_resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if not userinfo_resp.is_success:
            raise HTTPException(status_code=400, detail="Failed to fetch user info")

    userinfo = userinfo_resp.json()
    google_id = userinfo.get("sub")
    if not google_id:
        raise HTTPException(status_code=400, detail="No Google ID in user info")

    email = userinfo.get("email", "")
    name = userinfo.get("name") or email.split("@")[0] or google_id

    # Upsert user
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=email, name=name, google_id=google_id)
        db.add(user)
        await db.flush()
    else:
        user.email = email
        user.name = name

    await db.commit()
    await db.refresh(user)

    # Issue JWT as httpOnly cookie and redirect to dashboard
    token = _create_jwt(str(user.id))
    redirect = RedirectResponse(url=f"{settings.app_url}/dashboard", status_code=302)
    redirect.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expiry_hours * 3600,
        path="/",
    )
    return redirect


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "plan": user.plan,
        "role": user.role,
    }
