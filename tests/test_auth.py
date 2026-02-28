import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from jose import jwt

from app.config import get_settings
from app.db.session import get_db
from app.main import app


def _make_jwt(user_id: str | None = None, expired: bool = False) -> str:
    settings = get_settings()
    uid = user_id or str(uuid.uuid4())
    if expired:
        exp = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    else:
        exp = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    payload = {"sub": uid, "exp": exp}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _mock_db_no_user():
    """Mock DB session that returns no user for any query."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async def override_get_db():
        yield mock_session

    return override_get_db


client = TestClient(app)


def test_jwt_roundtrip():
    settings = get_settings()
    uid = str(uuid.uuid4())
    token = _make_jwt(uid)
    decoded = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert decoded["sub"] == uid


def test_me_unauthenticated():
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_with_expired_token():
    token = _make_jwt(expired=True)
    client.cookies.set("access_token", token)
    r = client.get("/auth/me")
    assert r.status_code == 401
    client.cookies.clear()


def test_me_with_invalid_token():
    client.cookies.set("access_token", "garbage")
    r = client.get("/auth/me")
    assert r.status_code == 401
    client.cookies.clear()


def test_me_with_valid_token_but_no_user():
    """Valid JWT but user doesn't exist in DB → 401."""
    app.dependency_overrides[get_db] = _mock_db_no_user()
    try:
        token = _make_jwt(str(uuid.uuid4()))
        client.cookies.set("access_token", token)
        r = client.get("/auth/me")
        assert r.status_code == 401
    finally:
        client.cookies.clear()
        app.dependency_overrides.pop(get_db, None)


def test_logout():
    r = client.post("/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_google_login_not_configured():
    """When GOOGLE_CLIENT_ID is not set, return 501."""
    from app.config import Settings

    empty_settings = Settings(google_client_id="", google_client_secret="")

    with patch("app.api.auth.get_settings", return_value=empty_settings):
        r = client.get("/auth/google")
    assert r.status_code == 501
