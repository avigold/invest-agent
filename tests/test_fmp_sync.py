"""Tests for FMP sync job handler."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jobs.handlers.fmp_sync import fmp_sync_handler


def _make_job(params: dict | None = None) -> MagicMock:
    job = MagicMock()
    job.params = params or {}
    job.log_lines = []
    job.queue = MagicMock()
    return job


def _make_company(ticker: str, country: str = "US") -> MagicMock:
    c = MagicMock()
    c.ticker = ticker
    c.country_iso2 = country
    c.id = uuid.uuid4()
    return c


@pytest.mark.asyncio
async def test_fmp_sync_processes_all_companies():
    """All companies from DB should be processed."""
    companies = [_make_company("AAPL"), _make_company("MSFT"), _make_company("GOOGL")]
    ingest_calls: list[str] = []

    async def mock_ingest(db, artefact_store, fmp_source, company, api_key, log_fn, force=False, client=None):
        ingest_calls.append(company.ticker)
        log_fn(f"  FMP fundamentals: {company.ticker}")
        log_fn(f"    revenue: 10 annual values")
        return [uuid.uuid4()]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = companies
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.commit = AsyncMock()

    mock_sf = MagicMock()
    mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_settings = MagicMock()
    mock_settings.fmp_api_key = "test-key"
    mock_settings.artefact_storage_dir = "/tmp/artefacts"

    mock_fmp_source = MagicMock()
    mock_fmp_source.id = uuid.uuid4()

    job = _make_job({"concurrency": 3})

    with (
        patch("app.jobs.handlers.fmp_sync.get_settings", return_value=mock_settings),
        patch("app.jobs.handlers.fmp_sync.ArtefactStore", return_value=MagicMock()),
        patch("app.jobs.handlers.fmp_sync.seed_data_sources", new_callable=AsyncMock, return_value={"fmp": mock_fmp_source}),
        patch("app.jobs.handlers.fmp_sync.ingest_fmp_fundamentals_for_company", side_effect=mock_ingest),
    ):
        await fmp_sync_handler(job, mock_sf)

    assert sorted(ingest_calls) == ["AAPL", "GOOGL", "MSFT"]


@pytest.mark.asyncio
async def test_fmp_sync_no_api_key():
    """Should log error and return if no API key configured."""
    mock_settings = MagicMock()
    mock_settings.fmp_api_key = ""

    job = _make_job()

    with patch("app.jobs.handlers.fmp_sync.get_settings", return_value=mock_settings):
        await fmp_sync_handler(job, MagicMock())

    assert any("FMP_API_KEY" in line for line in job.log_lines)


@pytest.mark.asyncio
async def test_fmp_sync_handles_failures():
    """Failed companies should be counted, not crash the batch."""
    companies = [_make_company("AAPL"), _make_company("BAD")]

    async def mock_ingest(db, artefact_store, fmp_source, company, api_key, log_fn, force=False, client=None):
        if company.ticker == "BAD":
            raise RuntimeError("API error")
        log_fn("  FMP fundamentals: AAPL")
        log_fn("    revenue: 10 annual values")
        return [uuid.uuid4()]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = companies
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.commit = AsyncMock()

    mock_sf = MagicMock()
    mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_settings = MagicMock()
    mock_settings.fmp_api_key = "test-key"
    mock_settings.artefact_storage_dir = "/tmp/artefacts"

    job = _make_job()

    with (
        patch("app.jobs.handlers.fmp_sync.get_settings", return_value=mock_settings),
        patch("app.jobs.handlers.fmp_sync.ArtefactStore", return_value=MagicMock()),
        patch("app.jobs.handlers.fmp_sync.seed_data_sources", new_callable=AsyncMock, return_value={"fmp": MagicMock()}),
        patch("app.jobs.handlers.fmp_sync.ingest_fmp_fundamentals_for_company", side_effect=mock_ingest),
    ):
        await fmp_sync_handler(job, mock_sf)

    # Should complete without raising
    assert any("FAILED" in line for line in job.log_lines)
    assert any("complete" in line.lower() for line in job.log_lines)
