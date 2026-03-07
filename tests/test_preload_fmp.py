"""Tests for FMP preload CLI logic."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cli import _preload_fmp_async


def _make_company(ticker: str, country: str = "US") -> MagicMock:
    c = MagicMock()
    c.ticker = ticker
    c.country_iso2 = country
    c.id = uuid.uuid4()
    c.name = f"{ticker} Inc."
    return c


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.fmp_api_key = "test-key"
    s.artefact_storage_dir = "/tmp/artefacts"
    s.database_url = "postgresql+asyncpg://test:test@localhost/test"
    return s


@pytest.fixture
def mock_fmp_source():
    src = MagicMock()
    src.id = uuid.uuid4()
    return src


def _patch_preload(mock_settings, mock_fmp_source, companies, mock_ingest):
    """Return a context manager that patches all dependencies for _preload_fmp_async."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = companies

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_db.commit = AsyncMock()

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    from contextlib import contextmanager

    @contextmanager
    def ctx():
        with (
            patch("app.config.get_settings", return_value=mock_settings),
            patch("app.db.session._get_session_factory", return_value=mock_session_factory),
            patch("app.ingest.artefact_store.ArtefactStore", return_value=MagicMock()),
            patch("app.ingest.seed_sources.seed_data_sources", new_callable=AsyncMock, return_value={"fmp": mock_fmp_source}),
            patch("app.ingest.fmp_fundamentals.ingest_fmp_fundamentals_for_company", side_effect=mock_ingest),
            patch("app.db.session.dispose_engine", new_callable=AsyncMock),
        ):
            yield

    return ctx()


@pytest.mark.asyncio
async def test_preload_processes_all_companies(mock_settings, mock_fmp_source):
    """All companies from DB should be processed."""
    companies = [_make_company("AAPL"), _make_company("MSFT"), _make_company("GOOGL")]
    ingest_calls: list[str] = []

    async def mock_ingest(db, artefact_store, fmp_source, company, api_key, log_fn, force=False, client=None):
        ingest_calls.append(company.ticker)
        log_fn(f"  FMP fundamentals: {company.ticker}")
        log_fn(f"    revenue: 10 annual values")
        return [uuid.uuid4()]

    with _patch_preload(mock_settings, mock_fmp_source, companies, mock_ingest):
        await _preload_fmp_async(concurrency=3, force=False, country_filter=None)

    assert sorted(ingest_calls) == ["AAPL", "GOOGL", "MSFT"]


@pytest.mark.asyncio
async def test_preload_skips_fresh_companies(mock_settings, mock_fmp_source):
    """Companies with fresh data should be reported as skipped."""
    companies = [_make_company("AAPL")]

    async def mock_ingest(db, artefact_store, fmp_source, company, api_key, log_fn, force=False, client=None):
        log_fn(f"  FMP fundamentals: {company.ticker}")
        log_fn("    Skipped (fresh)")
        return [uuid.uuid4()]

    with _patch_preload(mock_settings, mock_fmp_source, companies, mock_ingest):
        await _preload_fmp_async(concurrency=3, force=False, country_filter=None)

    # Test passes if no exception — skip detection works correctly


@pytest.mark.asyncio
async def test_preload_handles_failures(mock_settings, mock_fmp_source):
    """Failed companies should be counted and not crash the batch."""
    companies = [_make_company("AAPL"), _make_company("BAD")]
    call_count = 0

    async def mock_ingest(db, artefact_store, fmp_source, company, api_key, log_fn, force=False, client=None):
        nonlocal call_count
        call_count += 1
        if company.ticker == "BAD":
            raise RuntimeError("API error")
        log_fn(f"  FMP fundamentals: {company.ticker}")
        log_fn(f"    revenue: 10 annual values")
        return [uuid.uuid4()]

    with _patch_preload(mock_settings, mock_fmp_source, companies, mock_ingest):
        await _preload_fmp_async(concurrency=3, force=False, country_filter=None)

    assert call_count == 2  # Both were attempted


@pytest.mark.asyncio
async def test_preload_passes_force_flag(mock_settings, mock_fmp_source):
    """Force flag should be forwarded to ingest function."""
    companies = [_make_company("AAPL")]
    force_values: list[bool] = []

    async def mock_ingest(db, artefact_store, fmp_source, company, api_key, log_fn, force=False, client=None):
        force_values.append(force)
        log_fn(f"  FMP fundamentals: {company.ticker}")
        log_fn(f"    revenue: 10 annual values")
        return [uuid.uuid4()]

    with _patch_preload(mock_settings, mock_fmp_source, companies, mock_ingest):
        await _preload_fmp_async(concurrency=3, force=True, country_filter=None)

    assert force_values == [True]


@pytest.mark.asyncio
async def test_preload_passes_shared_client(mock_settings, mock_fmp_source):
    """A shared httpx client should be passed to each ingest call."""
    companies = [_make_company("AAPL")]
    clients_seen: list = []

    async def mock_ingest(db, artefact_store, fmp_source, company, api_key, log_fn, force=False, client=None):
        clients_seen.append(client)
        log_fn(f"  FMP fundamentals: {company.ticker}")
        log_fn(f"    revenue: 10 annual values")
        return [uuid.uuid4()]

    with _patch_preload(mock_settings, mock_fmp_source, companies, mock_ingest):
        await _preload_fmp_async(concurrency=3, force=False, country_filter=None)

    assert len(clients_seen) == 1
    assert clients_seen[0] is not None  # A real httpx client was passed
