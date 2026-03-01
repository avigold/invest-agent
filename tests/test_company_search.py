"""Tests for company search: SEC ticker cache, add endpoint, GICS mapping, company_refresh DB-only."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ingest.company_lookup import (
    SECCompanyEntry,
    SECTickerCache,
    map_country_to_iso2,
    map_sector_to_gics,
)


# ---------------------------------------------------------------------------
# GICS sector mapping
# ---------------------------------------------------------------------------


def test_map_sector_to_gics_known():
    assert map_sector_to_gics("Technology") == "45"
    assert map_sector_to_gics("Financial Services") == "40"
    assert map_sector_to_gics("Healthcare") == "35"
    assert map_sector_to_gics("Energy") == "10"


def test_map_sector_to_gics_case_insensitive():
    assert map_sector_to_gics("TECHNOLOGY") == "45"
    assert map_sector_to_gics("  healthcare  ") == "35"


def test_map_sector_to_gics_unknown():
    assert map_sector_to_gics("Space Mining") == ""
    assert map_sector_to_gics(None) == ""
    assert map_sector_to_gics("") == ""


# ---------------------------------------------------------------------------
# Country ISO2 mapping
# ---------------------------------------------------------------------------


def test_map_country_to_iso2_known():
    assert map_country_to_iso2("United States") == "US"
    assert map_country_to_iso2("Japan") == "JP"


def test_map_country_to_iso2_defaults_to_us():
    assert map_country_to_iso2("Unknown Country") == "US"
    assert map_country_to_iso2(None) == "US"


# ---------------------------------------------------------------------------
# SEC ticker cache search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sec_ticker_cache_search():
    """SECTickerCache.search should return exact matches first, then prefix, then name."""
    # Populate cache directly
    entries = [
        SECCompanyEntry(cik="0000320193", ticker="AAPL", name="Apple Inc"),
        SECCompanyEntry(cik="0000789019", ticker="MSFT", name="Microsoft Corp"),
        SECCompanyEntry(cik="0001018724", ticker="AMZN", name="Amazon Com Inc"),
        SECCompanyEntry(cik="0001652044", ticker="GOOG", name="Alphabet Inc"),
        SECCompanyEntry(cik="0000012345", ticker="AA", name="Alcoa Corp"),
    ]
    SECTickerCache._entries = entries
    SECTickerCache._by_ticker = {e.ticker: e for e in entries}
    SECTickerCache._fetched_at = 9999999999.0  # prevent refresh

    # Exact match
    results = await SECTickerCache.search("AAPL")
    assert results[0].ticker == "AAPL"

    # Prefix match
    results = await SECTickerCache.search("AA")
    assert results[0].ticker == "AA"  # exact first
    assert results[1].ticker == "AAPL"  # prefix second

    # Name substring
    results = await SECTickerCache.search("Microsoft")
    assert any(r.ticker == "MSFT" for r in results)

    # Empty query
    results = await SECTickerCache.search("")
    assert results == []


@pytest.mark.asyncio
async def test_sec_ticker_cache_lookup_cik():
    """lookup_cik should return CIK for known tickers, None for unknown."""
    entries = [
        SECCompanyEntry(cik="0000320193", ticker="AAPL", name="Apple Inc"),
    ]
    SECTickerCache._entries = entries
    SECTickerCache._by_ticker = {e.ticker: e for e in entries}
    SECTickerCache._fetched_at = 9999999999.0

    cik = await SECTickerCache.lookup_cik("AAPL")
    assert cik == "0000320193"

    cik = await SECTickerCache.lookup_cik("XXXX")
    assert cik is None


# ---------------------------------------------------------------------------
# Add companies endpoint (via route handler)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_companies_endpoint_deduplicates():
    """POST /v1/companies/add should skip already-existing tickers."""
    from app.api.routes_company_search import add_companies, AddCompaniesRequest, AddCompanyEntry

    # Mock DB session
    db = AsyncMock()

    # First call: existing CIKs query (returns empty set)
    mock_cik_result = MagicMock()
    mock_cik_result.all.return_value = []

    # Second call: first ticker exists
    mock_result_existing = MagicMock()
    mock_result_existing.scalar_one_or_none.return_value = MagicMock()  # exists

    # Third call: second ticker doesn't exist
    mock_result_new = MagicMock()
    mock_result_new.scalar_one_or_none.return_value = None  # doesn't exist

    db.execute.side_effect = [mock_cik_result, mock_result_existing, mock_result_new]

    user = MagicMock()
    user.id = uuid.uuid4()

    body = AddCompaniesRequest(companies=[
        AddCompanyEntry(ticker="AAPL", name="Apple Inc", cik="0000320193"),
        AddCompanyEntry(ticker="NEWCO", name="New Company"),
    ])

    result = await add_companies(body=body, user=user, db=db)

    assert result.added == 1
    assert result.skipped == 1
    assert "NEWCO" in result.tickers_added
    assert "AAPL" in result.tickers_skipped


# ---------------------------------------------------------------------------
# add_companies_by_market_cap handler registration
# ---------------------------------------------------------------------------


def test_add_companies_handler_registered():
    """add_companies_by_market_cap should be registered in HANDLERS."""
    from app.jobs.handlers import HANDLERS
    assert "add_companies_by_market_cap" in HANDLERS


def test_add_companies_in_heavy_commands():
    """add_companies_by_market_cap should be in HEAVY_COMMANDS."""
    from app.jobs.queue import HEAVY_COMMANDS
    assert "add_companies_by_market_cap" in HEAVY_COMMANDS


def test_add_companies_job_command_enum():
    """ADD_COMPANIES_BY_MARKET_CAP should be in JobCommand enum."""
    from app.jobs.schemas import JobCommand
    assert JobCommand.ADD_COMPANIES_BY_MARKET_CAP == "add_companies_by_market_cap"


# ---------------------------------------------------------------------------
# PRD 5.4: Version bumps and weight validation
# ---------------------------------------------------------------------------


def test_company_weights_no_industry_context():
    """COMPANY_WEIGHTS should not include industry_context (PRD 5.4)."""
    from app.score.versions import COMPANY_WEIGHTS
    assert "industry_context" not in COMPANY_WEIGHTS
    assert set(COMPANY_WEIGHTS.keys()) == {"fundamental", "market"}


def test_company_weights_sum_to_one():
    """COMPANY_WEIGHTS values should sum to 1.0."""
    from app.score.versions import COMPANY_WEIGHTS
    assert abs(sum(COMPANY_WEIGHTS.values()) - 1.0) < 1e-9


def test_company_weights_no_fundamentals_sum_to_one():
    """COMPANY_WEIGHTS_NO_FUNDAMENTALS values should sum to 1.0."""
    from app.score.versions import COMPANY_WEIGHTS_NO_FUNDAMENTALS
    assert abs(sum(COMPANY_WEIGHTS_NO_FUNDAMENTALS.values()) - 1.0) < 1e-9
    assert COMPANY_WEIGHTS_NO_FUNDAMENTALS["fundamental"] == 0.0


def test_version_bumps_v3():
    """Version constants should be bumped for PRD 5.4."""
    from app.score.versions import (
        COMPANY_CALC_VERSION,
        COMPANY_SUMMARY_VERSION,
        RECOMMENDATION_VERSION,
    )
    assert COMPANY_CALC_VERSION == "company_v3"
    assert COMPANY_SUMMARY_VERSION == "company_summary_v3"
    assert RECOMMENDATION_VERSION == "recommendation_v2"
