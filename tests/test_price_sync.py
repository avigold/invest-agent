"""Tests for price sync job handler."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jobs.handlers.price_sync import price_sync_handler


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
async def test_price_sync_processes_companies_and_countries():
    """Should process both country indices and company prices via FMP."""
    companies = [_make_company("AAPL"), _make_company("MSFT")]
    country_call_count = 0
    company_calls: list[str] = []

    async def mock_country_ingest(db, artefact_store, yf_source, country, start_date, end_date, log_fn, force=False):
        nonlocal country_call_count
        country_call_count += 1
        return [uuid.uuid4()]

    async def mock_fmp_ingest(db, artefact_store, fmp_source, company, api_key, log_fn, force=False, client=None):
        company_calls.append(company.ticker)
        log_fn(f"  {company.ticker}: 100 daily prices")
        return [uuid.uuid4()]

    # Mock country object returned from DB
    mock_country = MagicMock()
    mock_country.iso2 = "US"

    # Build mock DB with controlled execute responses
    mock_db = AsyncMock()

    country_result = MagicMock()
    country_result.scalar_one_or_none.return_value = mock_country

    company_result = MagicMock()
    company_result.scalars.return_value.all.return_value = companies

    # seed_data_sources is patched separately, so execute calls are:
    # 1: country query (US), 2: company query
    mock_db.execute = AsyncMock(side_effect=[country_result, company_result])
    mock_db.commit = AsyncMock()

    mock_sf = MagicMock()
    mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_settings = MagicMock()
    mock_settings.artefact_storage_dir = "/tmp/artefacts"
    mock_settings.fmp_api_key = "test-key"

    mock_fmp_source = MagicMock()

    # Minimal country config with one country
    test_config = '{"countries": [{"iso2": "US", "iso3": "USA", "name": "United States", "equity_index_symbol": "^GSPC"}]}'

    job = _make_job({"concurrency": 2})

    with (
        patch("app.jobs.handlers.price_sync.get_settings", return_value=mock_settings),
        patch("app.jobs.handlers.price_sync.ArtefactStore", return_value=MagicMock()),
        patch("app.jobs.handlers.price_sync.seed_data_sources", new_callable=AsyncMock, return_value={"yfinance": MagicMock(), "fmp": mock_fmp_source}),
        patch("app.jobs.handlers.price_sync.ingest_market_data_for_country", side_effect=mock_country_ingest),
        patch("app.jobs.handlers.price_sync.ingest_fmp_prices_for_company", side_effect=mock_fmp_ingest),
        patch("pathlib.Path.read_text", return_value=test_config),
    ):
        await price_sync_handler(job, mock_sf)

    assert country_call_count == 1  # US index
    assert sorted(company_calls) == ["AAPL", "MSFT"]
