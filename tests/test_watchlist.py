"""Tests for watchlist API endpoints (POST, GET, DELETE, check, reorder)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db.models import Company, User, WatchlistItem
from app.db.session import get_db
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user() -> User:
    return User(id=uuid.uuid4(), email="t@t.com", name="Test", plan="free", role="user")


def _mock_user(user: User):
    async def override():
        return user
    return override


def _make_company(ticker: str = "AAPL", country_iso2: str = "US", gics_code: str = "45") -> Company:
    return Company(
        id=uuid.uuid4(),
        ticker=ticker,
        name=f"{ticker} Inc",
        country_iso2=country_iso2,
        gics_code=gics_code,
    )


def _make_watchlist_item(
    user: User,
    company: Company,
    position: int = 0,
) -> WatchlistItem:
    return WatchlistItem(
        id=uuid.uuid4(),
        user_id=user.id,
        company_id=company.id,
        ticker=company.ticker,
        position=position,
        added_at=datetime.now(timezone.utc),
    )


client = TestClient(app)


# ---------------------------------------------------------------------------
# POST /v1/watchlist — add ticker
# ---------------------------------------------------------------------------


def test_add_to_watchlist_success():
    """POST /v1/watchlist should create a watchlist item for a valid ticker."""
    user = _make_user()
    company = _make_company("AAPL")

    mock_session = AsyncMock()
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # Company lookup — found
            result.scalar_one_or_none.return_value = company
        elif call_count == 2:
            # Duplicate check — not found
            result.scalar_one_or_none.return_value = None
        elif call_count == 3:
            # Count query
            result.scalar.return_value = 0
        elif call_count == 4:
            # Max position query
            result.scalar.return_value = -1
        return result

    mock_session.execute = mock_execute

    item = WatchlistItem(
        id=uuid.uuid4(),
        user_id=user.id,
        company_id=company.id,
        ticker="AAPL",
        position=0,
        added_at=datetime.now(timezone.utc),
    )

    async def mock_refresh(obj):
        obj.id = item.id
        obj.ticker = "AAPL"
        obj.position = 0

    mock_session.refresh = mock_refresh

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.post("/v1/watchlist", json={"ticker": "AAPL"})
        assert r.status_code == 201
        body = r.json()
        assert body["ticker"] == "AAPL"
        assert body["position"] == 0
        assert "id" in body
    finally:
        app.dependency_overrides.clear()


def test_add_to_watchlist_ticker_not_found():
    """POST /v1/watchlist should return 404 when the ticker does not exist."""
    user = _make_user()

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        # Company lookup — not found
        result.scalar_one_or_none.return_value = None
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.post("/v1/watchlist", json={"ticker": "ZZZZZ"})
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_add_to_watchlist_duplicate():
    """POST /v1/watchlist should return 409 when the ticker is already in the watchlist."""
    user = _make_user()
    company = _make_company("AAPL")
    existing_item = _make_watchlist_item(user, company)

    mock_session = AsyncMock()
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # Company lookup — found
            result.scalar_one_or_none.return_value = company
        elif call_count == 2:
            # Duplicate check — found (already exists)
            result.scalar_one_or_none.return_value = existing_item
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.post("/v1/watchlist", json={"ticker": "AAPL"})
        assert r.status_code == 409
        assert "already" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_add_to_watchlist_requires_auth():
    """POST /v1/watchlist should return 401 without authentication."""
    r = client.post("/v1/watchlist", json={"ticker": "AAPL"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/watchlist — list watchlist
# ---------------------------------------------------------------------------


def test_list_watchlist_empty():
    """GET /v1/watchlist should return an empty list when the user has no items."""
    user = _make_user()

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        result.all.return_value = []
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.get("/v1/watchlist")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()


def test_list_watchlist_with_items():
    """GET /v1/watchlist should return enriched items when the user has watchlist entries."""
    user = _make_user()
    company = _make_company("AAPL")
    wi = _make_watchlist_item(user, company, position=0)

    mock_session = AsyncMock()
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()

        if call_count == 1:
            # Main watchlist query with company + price join
            # Returns tuples of (WatchlistItem, Company, CompanyPriceHistory)
            result.all.return_value = [(wi, company, None)]
        elif call_count == 2:
            # Company scores subquery + join
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = []
            result.scalars.return_value = scalars_mock
        elif call_count == 3:
            # Country scores query
            result.all.return_value = []
        elif call_count == 4:
            # Industry scores query
            result.all.return_value = []
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.get("/v1/watchlist")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["ticker"] == "AAPL"
        assert data[0]["name"] == "AAPL Inc"
        assert data[0]["country_iso2"] == "US"
        assert data[0]["position"] == 0
        assert "id" in data[0]
        assert "added_at" in data[0]
    finally:
        app.dependency_overrides.clear()


def test_list_watchlist_requires_auth():
    """GET /v1/watchlist should return 401 without authentication."""
    r = client.get("/v1/watchlist")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /v1/watchlist/{ticker} — remove from watchlist
# ---------------------------------------------------------------------------


def test_remove_from_watchlist_success():
    """DELETE /v1/watchlist/{ticker} should remove the item and return 204."""
    user = _make_user()
    company = _make_company("AAPL")
    existing_item = _make_watchlist_item(user, company)

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_item
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.delete("/v1/watchlist/AAPL")
        assert r.status_code == 204
    finally:
        app.dependency_overrides.clear()


def test_remove_from_watchlist_not_found():
    """DELETE /v1/watchlist/{ticker} should return 404 when the ticker is not in the watchlist."""
    user = _make_user()

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.delete("/v1/watchlist/ZZZZZ")
        assert r.status_code == 404
        assert "not in your watchlist" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_remove_from_watchlist_requires_auth():
    """DELETE /v1/watchlist/{ticker} should return 401 without authentication."""
    r = client.delete("/v1/watchlist/AAPL")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/watchlist/check/{ticker} — check if ticker is in watchlist
# ---------------------------------------------------------------------------


def test_check_watchlist_in_watchlist():
    """GET /v1/watchlist/check/{ticker} should return in_watchlist=true when present."""
    user = _make_user()
    item_id = uuid.uuid4()

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = item_id
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.get("/v1/watchlist/check/AAPL")
        assert r.status_code == 200
        assert r.json()["in_watchlist"] is True
    finally:
        app.dependency_overrides.clear()


def test_check_watchlist_not_in_watchlist():
    """GET /v1/watchlist/check/{ticker} should return in_watchlist=false when absent."""
    user = _make_user()

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.get("/v1/watchlist/check/ZZZZZ")
        assert r.status_code == 200
        assert r.json()["in_watchlist"] is False
    finally:
        app.dependency_overrides.clear()


def test_check_watchlist_requires_auth():
    """GET /v1/watchlist/check/{ticker} should return 401 without authentication."""
    r = client.get("/v1/watchlist/check/AAPL")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# PUT /v1/watchlist/reorder — reorder watchlist items
# ---------------------------------------------------------------------------


def test_reorder_watchlist_success():
    """PUT /v1/watchlist/reorder should update positions and return ok."""
    user = _make_user()
    company_a = _make_company("AAPL")
    company_b = _make_company("MSFT")
    wi_a = _make_watchlist_item(user, company_a, position=0)
    wi_b = _make_watchlist_item(user, company_b, position=1)

    id_a = str(wi_a.id)
    id_b = str(wi_b.id)

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [wi_a, wi_b]
        result.scalars.return_value = scalars_mock
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        # Reverse the order
        r = client.put("/v1/watchlist/reorder", json={"order": [id_b, id_a]})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # Verify positions were updated
        assert wi_b.position == 0
        assert wi_a.position == 1
    finally:
        app.dependency_overrides.clear()


def test_reorder_watchlist_invalid_ids():
    """PUT /v1/watchlist/reorder should return 422 when IDs do not match the user's items."""
    user = _make_user()
    company = _make_company("AAPL")
    wi = _make_watchlist_item(user, company, position=0)

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [wi]
        result.scalars.return_value = scalars_mock
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        # Send a completely wrong ID
        bogus_id = str(uuid.uuid4())
        r = client.put("/v1/watchlist/reorder", json={"order": [bogus_id]})
        assert r.status_code == 422
        assert "exactly all" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_reorder_watchlist_requires_auth():
    """PUT /v1/watchlist/reorder should return 401 without authentication."""
    r = client.put("/v1/watchlist/reorder", json={"order": []})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/watchlist/bulk — bulk add tickers
# ---------------------------------------------------------------------------


def test_bulk_add_success():
    """POST /v1/watchlist/bulk should add multiple tickers, skipping duplicates."""
    user = _make_user()
    company_a = _make_company("AAPL")
    company_b = _make_company("MSFT")
    # AAPL already in watchlist
    existing_item = _make_watchlist_item(user, company_a)

    mock_session = AsyncMock()
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # Company lookup by ticker IN
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [company_a, company_b]
            result.scalars.return_value = scalars_mock
        elif call_count == 2:
            # Existing watchlist company_ids
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [company_a.id]
            result.scalars.return_value = scalars_mock
        elif call_count == 3:
            # Max position
            result.scalar.return_value = 0
        return result

    mock_session.execute = mock_execute

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.post("/v1/watchlist/bulk", json={"tickers": ["AAPL", "MSFT"]})
        assert r.status_code == 200
        body = r.json()
        assert body["added"] == 1
        assert body["skipped"] == 1
        assert "MSFT" in body["tickers_added"]
        assert "AAPL" not in body["tickers_added"]
    finally:
        app.dependency_overrides.clear()


def test_bulk_add_empty():
    """POST /v1/watchlist/bulk with empty tickers should return zeros."""
    user = _make_user()

    mock_session = AsyncMock()

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_current_user] = _mock_user(user)
    app.dependency_overrides[get_db] = override_get_db

    try:
        r = client.post("/v1/watchlist/bulk", json={"tickers": []})
        assert r.status_code == 200
        body = r.json()
        assert body["added"] == 0
        assert body["skipped"] == 0
    finally:
        app.dependency_overrides.clear()


def test_bulk_add_requires_auth():
    """POST /v1/watchlist/bulk should return 401 without authentication."""
    r = client.post("/v1/watchlist/bulk", json={"tickers": ["AAPL"]})
    assert r.status_code == 401
