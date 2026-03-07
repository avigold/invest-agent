"""Tests for data freshness system."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ingest.freshness import FRESHNESS_HOURS, is_stale


# ── is_stale tests ──────────────────────────────────────────────────────────

def test_is_stale_returns_true_for_old_data():
    """Data older than the freshness window should be stale."""
    fetched = datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_HOURS["world_bank"] + 1)
    assert is_stale("world_bank", fetched) is True


def test_is_stale_returns_false_for_fresh_data():
    """Data within the freshness window should not be stale."""
    fetched = datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_HOURS["world_bank"] - 1)
    assert is_stale("world_bank", fetched) is False


def test_is_stale_returns_true_for_unknown_source():
    """Unknown source should always be considered stale."""
    fetched = datetime.now(timezone.utc)
    assert is_stale("unknown_source", fetched) is True


def test_is_stale_handles_naive_datetime():
    """Naive datetime should be treated as UTC."""
    fetched = datetime.utcnow() - timedelta(hours=1)
    assert is_stale("world_bank", fetched) is False


def test_freshness_hours_configured():
    """All expected sources should have freshness windows."""
    expected = {"world_bank", "imf_weo", "fred", "yfinance_market", "gdelt", "sec_edgar", "yfinance_fundamentals", "fmp_fundamentals"}
    assert expected == set(FRESHNESS_HOURS.keys())


# ── Freshness check in ingest functions ─────────────────────────────────────

@pytest.mark.asyncio
async def test_gdelt_skips_when_fresh():
    """GDELT ingest should skip when a fresh artefact exists."""
    from app.ingest.gdelt import ingest_gdelt_stability

    fresh_artefact = MagicMock()
    fresh_artefact.id = uuid.uuid4()

    mock_store = AsyncMock()
    mock_store.find_fresh.return_value = fresh_artefact

    db = AsyncMock()
    gdelt_source = MagicMock()
    gdelt_source.id = uuid.uuid4()
    country = MagicMock()
    country.iso2 = "US"

    from datetime import date
    logs: list[str] = []
    ids = await ingest_gdelt_stability(
        db=db,
        artefact_store=mock_store,
        gdelt_source=gdelt_source,
        country=country,
        as_of=date(2026, 3, 1),
        log_fn=logs.append,
    )

    assert ids == [fresh_artefact.id]
    assert any("skipped" in log.lower() or "fresh" in log.lower() for log in logs)
    # Should NOT have called store (no fetch happened)
    mock_store.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_gdelt_fetches_when_force():
    """GDELT ingest should fetch even when fresh if force=True."""
    from app.ingest.gdelt import ingest_gdelt_stability

    fresh_artefact = MagicMock()
    fresh_artefact.id = uuid.uuid4()

    stored_artefact = MagicMock()
    stored_artefact.id = uuid.uuid4()

    mock_store = AsyncMock()
    mock_store.find_fresh.return_value = fresh_artefact
    mock_store.store.return_value = stored_artefact

    mock_series = MagicMock()
    mock_series.id = uuid.uuid4()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_series

    db = AsyncMock()
    db.execute.return_value = mock_result

    gdelt_source = MagicMock()
    gdelt_source.id = uuid.uuid4()
    country = MagicMock()
    country.iso2 = "US"
    country.id = uuid.uuid4()

    from datetime import date
    logs: list[str] = []

    with patch("app.ingest.gdelt._fetch_gdelt_csv", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = [
            "Date,Series,Value\n2026-03-01,instability,1.5",
            "Date,Series,Value\n2026-03-01,total,30.0",
        ]

        ids = await ingest_gdelt_stability(
            db=db,
            artefact_store=mock_store,
            gdelt_source=gdelt_source,
            country=country,
            as_of=date(2026, 3, 1),
            log_fn=logs.append,
            force=True,
        )

    # find_fresh should NOT have been called (force bypasses it)
    mock_store.find_fresh.assert_not_awaited()
    # store should have been called (data was fetched)
    mock_store.store.assert_awaited_once()


@pytest.mark.asyncio
async def test_world_bank_skips_when_fresh():
    """World Bank ingest should skip indicators that have fresh artefacts."""
    from app.ingest.world_bank import ingest_world_bank_for_country

    fresh_artefact = MagicMock()
    fresh_artefact.id = uuid.uuid4()

    mock_store = AsyncMock()
    mock_store.find_fresh.return_value = fresh_artefact

    db = AsyncMock()
    wb_source = MagicMock()
    wb_source.id = uuid.uuid4()
    country = MagicMock()
    country.iso2 = "US"
    country.id = uuid.uuid4()

    logs: list[str] = []
    ids = await ingest_world_bank_for_country(
        db=db,
        artefact_store=mock_store,
        wb_source=wb_source,
        country=country,
        indicators={"gdp_growth": "NY.GDP.MKTP.KD.ZG"},
        start_year=2015,
        end_year=2026,
        log_fn=logs.append,
    )

    assert ids == [fresh_artefact.id]
    assert any("skipped" in log.lower() or "fresh" in log.lower() for log in logs)
    mock_store.store.assert_not_awaited()
