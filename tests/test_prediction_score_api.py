"""Tests for the single-ticker ML score endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db.models import PredictionModel, PredictionScore, User
from app.db.session import get_db
from app.main import app


def _make_user() -> User:
    return User(id=uuid.uuid4(), email="t@t.com", name="Test", plan="free", role="user")


def _mock_user(user: User):
    async def override():
        return user
    return override


def _make_model(user_id: uuid.UUID):
    """Create a mock PredictionModel without SQLAlchemy instrumentation."""
    from unittest.mock import MagicMock
    m = MagicMock(spec=[])
    m.id = uuid.uuid4()
    m.user_id = user_id
    m.model_version = "seed32_v1"
    m.created_at = datetime(2026, 3, 8)
    m.config = {}
    m.fold_metrics = {}
    m.aggregate_metrics = {"mean_auc": 0.72}
    m.feature_importance = {}
    m.backtest_results = {}
    m.platt_a = -4.8
    m.platt_b = 2.3
    m.job_id = None
    return m


def _make_score(model_id: uuid.UUID, ticker: str = "AAPL"):
    """Create a mock PredictionScore without SQLAlchemy instrumentation."""
    from unittest.mock import MagicMock
    s = MagicMock(spec=[])
    s.id = uuid.uuid4()
    s.model_id = model_id
    s.ticker = ticker
    s.company_name = "Apple Inc."
    s.country = "US"
    s.sector = "Information Technology"
    s.probability = 0.544
    s.confidence_tier = "high"
    s.kelly_fraction = 0.1
    s.suggested_weight = 0.02
    s.contributing_features = {"roe": {"value": 0.95, "importance": 0.12}}
    s.feature_values = {"roe": 0.95, "net_margin": 0.28, "debt_equity": 1.5}
    s.scored_at = datetime(2026, 3, 8)
    s.job_id = None
    return s


class _MockResult:
    """Mock for SQLAlchemy result objects."""
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value if isinstance(self._value, list) else []


def _mock_db_for_score(model, score):
    """Mock DB that handles the sequence of queries in get_score_for_ticker."""
    call_count = 0

    async def mock_execute(query, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        # 1st call: find latest model
        if call_count == 1:
            return _MockResult(model)
        # 2nd call: find score for ticker
        if call_count == 2:
            return _MockResult(score)
        return _MockResult(None)

    db = AsyncMock()
    db.execute = mock_execute
    return db


class TestGetScoreForTicker:
    def test_returns_score_with_feature_values(self):
        user = _make_user()
        model = _make_model(user.id)
        score = _make_score(model.id)
        db = _mock_db_for_score(model, score)

        app.dependency_overrides[get_current_user] = _mock_user(user)
        app.dependency_overrides[get_db] = lambda: db

        try:
            client = TestClient(app)
            resp = client.get("/v1/predictions/score/AAPL")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ticker"] == "AAPL"
            assert data["probability"] == 0.544
            assert "feature_values" in data
            assert data["feature_values"]["roe"] == 0.95
            assert data["model_version"] == "seed32_v1"
            # Fundamentals always computed from feature_values
            assert data["fundamentals"] is not None
            assert data["fundamentals"]["classification"] in ("Buy", "Hold", "Sell")
            assert "fundamental_score" in data["fundamentals"]
            assert "market_score" in data["fundamentals"]
            assert "company_score" in data["fundamentals"]
        finally:
            app.dependency_overrides.clear()

    def test_fundamentals_composite_scoring(self):
        user = _make_user()
        model = _make_model(user.id)
        score = _make_score(model.id)
        db = _mock_db_for_score(model, score)

        app.dependency_overrides[get_current_user] = _mock_user(user)
        app.dependency_overrides[get_db] = lambda: db

        try:
            client = TestClient(app)
            resp = client.get("/v1/predictions/score/AAPL")
            assert resp.status_code == 200
            data = resp.json()
            f = data["fundamentals"]
            assert f is not None
            # Full composite breakdown
            assert "composite_score" in f
            assert "company_score" in f
            assert "fundamental_score" in f
            assert "market_score" in f
            assert "country_score" in f
            assert "industry_score" in f
            assert f["classification"] in ("Buy", "Hold", "Sell")
            # With no DB country/industry data, defaults to 50.0
            assert f["country_score"] == 50.0
            assert f["industry_score"] == 50.0
        finally:
            app.dependency_overrides.clear()

    def test_404_when_ticker_not_found(self):
        user = _make_user()
        model = _make_model(user.id)
        db = _mock_db_for_score(model, None)  # no score found

        app.dependency_overrides[get_current_user] = _mock_user(user)
        app.dependency_overrides[get_db] = lambda: db

        try:
            client = TestClient(app)
            resp = client.get("/v1/predictions/score/NONEXIST")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_404_when_no_models(self):
        user = _make_user()
        db = _mock_db_for_score(None, None)  # no model found

        app.dependency_overrides[get_current_user] = _mock_user(user)
        app.dependency_overrides[get_db] = lambda: db

        try:
            client = TestClient(app)
            resp = client.get("/v1/predictions/score/AAPL")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_ticker_case_insensitive(self):
        user = _make_user()
        model = _make_model(user.id)
        score = _make_score(model.id)
        db = _mock_db_for_score(model, score)

        app.dependency_overrides[get_current_user] = _mock_user(user)
        app.dependency_overrides[get_db] = lambda: db

        try:
            client = TestClient(app)
            resp = client.get("/v1/predictions/score/aapl")
            assert resp.status_code == 200
            assert resp.json()["ticker"] == "AAPL"
        finally:
            app.dependency_overrides.clear()

    def test_deterministic_classification_in_response(self):
        user = _make_user()
        model = _make_model(user.id)
        score = _make_score(model.id)
        db = _mock_db_for_score(model, score)

        app.dependency_overrides[get_current_user] = _mock_user(user)
        app.dependency_overrides[get_db] = lambda: db

        try:
            client = TestClient(app)
            resp = client.get("/v1/predictions/score/AAPL")
            assert resp.status_code == 200
            data = resp.json()
            assert "deterministic_classification" in data
            assert data["deterministic_classification"] in ("Buy", "Hold", "Sell")
        finally:
            app.dependency_overrides.clear()
