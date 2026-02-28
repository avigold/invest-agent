"""Tests for country API routes."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db.models import Country, CountryScore, DecisionPacket, User
from app.db.session import get_db
from app.main import app


def _make_user() -> User:
    return User(id=uuid.uuid4(), email="t@t.com", name="Test", plan="free", role="user")


def _mock_user(user: User):
    async def override():
        return user
    return override


def _mock_db_countries(countries_with_scores: list[tuple] | None = None, packet: DecisionPacket | None = None):
    """Mock DB that handles multiple query types."""
    call_count = 0

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()

        stmt_str = str(stmt)

        # Latest date query (returns date)
        if "country_scores" in stmt_str and "LIMIT" in stmt_str and "country" not in stmt_str.split("JOIN")[0] if "JOIN" in stmt_str else True:
            if countries_with_scores:
                result.scalar_one_or_none.return_value = date(2026, 2, 1)
            else:
                result.scalar_one_or_none.return_value = None
            return result

        # Scores + countries join
        if countries_with_scores and "country_scores" in stmt_str and "countries" in stmt_str:
            result.all.return_value = countries_with_scores
            return result

        # Country lookup by iso2
        if "countries" in stmt_str and "iso2" in stmt_str:
            if packet:
                c = MagicMock()
                c.id = packet.entity_id
                c.iso2 = "US"
                result.scalar_one_or_none.return_value = c
            else:
                result.scalar_one_or_none.return_value = None
            return result

        # Decision packet query
        if "decision_packets" in stmt_str:
            result.scalar_one_or_none.return_value = packet
            return result

        result.scalar_one_or_none.return_value = None
        result.all.return_value = []
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    return override_get_db


client = TestClient(app)


def test_list_countries_empty():
    user = _make_user()
    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db_countries()

    try:
        r = client.get("/v1/countries")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()


def test_list_countries_requires_auth():
    r = client.get("/v1/countries")
    assert r.status_code == 401


def test_country_summary_not_found():
    user = _make_user()
    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = _mock_db_countries()

    try:
        r = client.get("/v1/country/XX/summary")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_country_summary_requires_auth():
    r = client.get("/v1/country/US/summary")
    assert r.status_code == 401
