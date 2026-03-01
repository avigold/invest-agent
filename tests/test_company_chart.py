"""Tests for company chart endpoint and market status utility."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.utils.market_hours import get_market_status, EXCHANGE_SCHEDULES


# ---------------------------------------------------------------------------
# Market status utility
# ---------------------------------------------------------------------------


def test_market_open_weekday_during_hours():
    """Weekday at 10am ET should be open."""
    et = ZoneInfo("America/New_York")
    # Use a known Wednesday
    mock_now = datetime(2026, 3, 4, 10, 0, 0, tzinfo=et)  # Wednesday 10am ET
    with patch("app.utils.market_hours.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        status = get_market_status("US")
    assert status["is_open"] is True
    assert status["exchange"] == "NYSE"


def test_market_closed_weekday_after_hours():
    """Weekday at 6pm ET should be closed."""
    et = ZoneInfo("America/New_York")
    mock_now = datetime(2026, 3, 4, 18, 0, 0, tzinfo=et)  # Wednesday 6pm ET
    with patch("app.utils.market_hours.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        status = get_market_status("US")
    assert status["is_open"] is False


def test_market_closed_weekend():
    """Saturday should be closed."""
    et = ZoneInfo("America/New_York")
    mock_now = datetime(2026, 3, 7, 12, 0, 0, tzinfo=et)  # Saturday noon ET
    with patch("app.utils.market_hours.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        status = get_market_status("US")
    assert status["is_open"] is False


def test_market_closed_before_open():
    """Weekday at 8am ET (before 9:30 open) should be closed."""
    et = ZoneInfo("America/New_York")
    mock_now = datetime(2026, 3, 4, 8, 0, 0, tzinfo=et)  # Wednesday 8am ET
    with patch("app.utils.market_hours.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        status = get_market_status("US")
    assert status["is_open"] is False


def test_market_status_unknown_country_defaults_nyse():
    """Unknown country should fall back to NYSE."""
    status = get_market_status("XX")
    assert status["exchange"] == "NYSE"


def test_market_status_has_required_fields():
    """Verify all required fields are present."""
    status = get_market_status("US")
    assert "is_open" in status
    assert "exchange" in status
    assert "next_open" in status
    assert "last_close_time" in status


# ---------------------------------------------------------------------------
# Period validation
# ---------------------------------------------------------------------------


def test_period_days_mapping():
    """Verify the PERIOD_DAYS constant covers expected periods."""
    from app.api.routes_companies import PERIOD_DAYS

    assert set(PERIOD_DAYS.keys()) == {"1w", "1m", "3m", "6m", "1y", "5y"}
    assert PERIOD_DAYS["1w"] == 7
    assert PERIOD_DAYS["1y"] == 365
    assert PERIOD_DAYS["5y"] == 1825
