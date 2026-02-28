import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.main import app


def _make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        name="Test",
        plan="free",
        role="user",
    )


def _mock_db():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async def override_get_db():
        yield mock_session

    return override_get_db


def _mock_user(user: User):
    async def override():
        return user
    return override


client = TestClient(app)


def test_checkout_not_configured():
    """When STRIPE_SECRET_KEY is not set, return 501."""
    user = _make_user()
    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db()

    try:
        r = client.post("/api/stripe/create-checkout-session")
        assert r.status_code == 501
    finally:
        app.dependency_overrides.clear()


def test_portal_not_configured():
    user = _make_user()
    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db()

    try:
        r = client.post("/api/stripe/create-portal-session")
        assert r.status_code == 501
    finally:
        app.dependency_overrides.clear()


def test_checkout_requires_auth():
    r = client.post("/api/stripe/create-checkout-session")
    assert r.status_code == 401


def test_webhook_not_configured():
    r = client.post(
        "/api/stripe/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "test"},
    )
    assert r.status_code == 501
