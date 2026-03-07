"""Tests for score sync job handler."""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jobs.handlers.score_sync import score_sync_handler


def _make_job(params: dict | None = None) -> MagicMock:
    job = MagicMock()
    job.params = params or {}
    job.log_lines = []
    job.queue = MagicMock()
    return job


def _make_company(ticker: str) -> MagicMock:
    c = MagicMock()
    c.ticker = ticker
    c.id = uuid.uuid4()
    return c


def _make_score(company_id: uuid.UUID, overall: float = 50.0) -> MagicMock:
    s = MagicMock()
    s.company_id = company_id
    s.overall_score = overall
    return s


@pytest.mark.asyncio
async def test_score_sync_skips_already_scored():
    """Companies with current scores should be skipped unless force=True."""
    companies = [_make_company("AAPL"), _make_company("MSFT")]
    # AAPL already scored
    scored_id = companies[0].id

    # Track which companies get scored
    scored_tickers: list[str] = []

    async def mock_compute(db, companies, as_of, log_fn):
        for c in companies:
            scored_tickers.append(c.ticker)
        return [_make_score(c.id) for c in companies]

    mock_db = AsyncMock()
    call_count = 0

    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # Company query
            result.scalars.return_value.all.return_value = companies
        elif call_count == 2:
            # Already scored query — return AAPL's id
            result.all.return_value = [(scored_id,)]
        else:
            # Other queries (delete, global scores, etc.)
            result.scalars.return_value.all.return_value = []
            result.all.return_value = []
        return result

    mock_db.execute = AsyncMock(side_effect=mock_execute)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    mock_sf = MagicMock()
    mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

    job = _make_job()

    with (
        patch("app.jobs.handlers.score_sync.compute_company_scores", side_effect=mock_compute),
        patch("app.jobs.handlers.score_sync.detect_company_risks", return_value=[]),
        patch("app.jobs.handlers.score_sync.build_company_packet", new_callable=AsyncMock, return_value=MagicMock()),
        patch("app.jobs.handlers.score_sync.COMPANY_CALC_VERSION", "test_v1"),
    ):
        await score_sync_handler(job, mock_sf)

    # Only MSFT should be scored (AAPL already has a score)
    assert scored_tickers == ["MSFT"]


@pytest.mark.asyncio
async def test_score_sync_force_rescores_all():
    """With force=True, all companies should be scored."""
    companies = [_make_company("AAPL"), _make_company("MSFT")]
    scored_tickers: list[str] = []

    async def mock_compute(db, companies, as_of, log_fn):
        for c in companies:
            scored_tickers.append(c.ticker)
        return [_make_score(c.id) for c in companies]

    mock_db = AsyncMock()
    call_count = 0

    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalars.return_value.all.return_value = companies
        else:
            result.scalars.return_value.all.return_value = []
            result.all.return_value = []
        return result

    mock_db.execute = AsyncMock(side_effect=mock_execute)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    mock_sf = MagicMock()
    mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

    job = _make_job({"force": True})

    with (
        patch("app.jobs.handlers.score_sync.compute_company_scores", side_effect=mock_compute),
        patch("app.jobs.handlers.score_sync.detect_company_risks", return_value=[]),
        patch("app.jobs.handlers.score_sync.build_company_packet", new_callable=AsyncMock, return_value=MagicMock()),
        patch("app.jobs.handlers.score_sync.COMPANY_CALC_VERSION", "test_v1"),
    ):
        await score_sync_handler(job, mock_sf)

    # Both should be scored with force
    assert sorted(scored_tickers) == ["AAPL", "MSFT"]
