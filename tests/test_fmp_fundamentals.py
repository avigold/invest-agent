"""Tests for FMP fundamentals extraction (pure logic, no network/DB)."""
from datetime import date

import pytest

from app.ingest.fmp_fundamentals import _extract_series_from_fmp, _fiscal_year
from app.screen.fundamentals_snapshot import extract_fmp_fundamentals_near_date


# ---------------------------------------------------------------------------
# Sample FMP data fixtures
# ---------------------------------------------------------------------------

def _make_income(year: int, **overrides) -> dict:
    base = {
        "date": f"{year}-12-31",
        "symbol": "AAPL",
        "reportedCurrency": "USD",
        "fiscalYear": str(year),
        "period": "FY",
        "revenue": 400_000_000_000,
        "netIncome": 100_000_000_000,
        "operatingIncome": 120_000_000_000,
        "epsDiluted": 6.50,
    }
    base.update(overrides)
    return base


def _make_balance(year: int, **overrides) -> dict:
    base = {
        "date": f"{year}-12-31",
        "symbol": "AAPL",
        "fiscalYear": str(year),
        "period": "FY",
        "totalAssets": 350_000_000_000,
        "totalLiabilities": 250_000_000_000,
        "totalStockholdersEquity": 100_000_000_000,
    }
    base.update(overrides)
    return base


def _make_cashflow(year: int, **overrides) -> dict:
    base = {
        "date": f"{year}-12-31",
        "symbol": "AAPL",
        "fiscalYear": str(year),
        "period": "FY",
        "operatingCashFlow": 110_000_000_000,
        "capitalExpenditure": 10_000_000_000,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _fiscal_year
# ---------------------------------------------------------------------------

class TestFiscalYear:
    def test_fiscal_year_field(self):
        assert _fiscal_year({"fiscalYear": "2024"}) == 2024

    def test_calendar_year_field(self):
        assert _fiscal_year({"calendarYear": "2023"}) == 2023

    def test_prefers_fiscal_year_over_calendar_year(self):
        assert _fiscal_year({"fiscalYear": "2024", "calendarYear": "2023"}) == 2024

    def test_fallback_to_date(self):
        assert _fiscal_year({"date": "2022-09-30"}) == 2022

    def test_invalid_returns_none(self):
        assert _fiscal_year({}) is None
        assert _fiscal_year({"fiscalYear": "abc"}) is None

    def test_short_date_returns_none(self):
        assert _fiscal_year({"date": "20"}) is None


# ---------------------------------------------------------------------------
# _extract_series_from_fmp
# ---------------------------------------------------------------------------

class TestExtractSeriesFromFmp:
    def test_basic_extraction(self):
        income = [_make_income(2024), _make_income(2023)]
        balance = [_make_balance(2024), _make_balance(2023)]
        cashflow = [_make_cashflow(2024), _make_cashflow(2023)]

        result = _extract_series_from_fmp(income, balance, cashflow)

        assert "revenue" in result
        assert "net_income" in result
        assert "operating_income" in result
        assert "eps_diluted" in result
        assert "total_assets" in result
        assert "total_liabilities" in result
        assert "stockholders_equity" in result
        assert "cash_from_ops" in result
        assert "capex" in result
        assert len(result) == 9

    def test_sorted_by_year_descending(self):
        income = [_make_income(2022), _make_income(2024), _make_income(2023)]
        result = _extract_series_from_fmp(income, [], [])
        years = [p["fiscal_year"] for p in result["revenue"]]
        assert years == [2024, 2023, 2022]

    def test_empty_statements(self):
        result = _extract_series_from_fmp([], [], [])
        assert result == {}

    def test_partial_data_income_only(self):
        income = [_make_income(2024)]
        result = _extract_series_from_fmp(income, [], [])

        assert "revenue" in result
        assert "net_income" in result
        assert "total_assets" not in result
        assert "cash_from_ops" not in result

    def test_missing_fields_skipped(self):
        income = [{"date": "2024-12-31", "fiscalYear": "2024", "revenue": 100}]
        result = _extract_series_from_fmp(income, [], [])

        assert "revenue" in result
        assert result["revenue"][0]["value"] == 100
        assert "net_income" not in result  # netIncome was not in the dict

    def test_none_values_skipped(self):
        income = [_make_income(2024, revenue=None)]
        result = _extract_series_from_fmp(income, [], [])
        assert "revenue" not in result

    def test_value_conversion(self):
        income = [_make_income(2024, revenue=123456789)]
        result = _extract_series_from_fmp(income, [], [])
        assert result["revenue"][0]["value"] == 123456789.0

    def test_multiple_years(self):
        income = [_make_income(y) for y in range(2020, 2025)]
        result = _extract_series_from_fmp(income, [], [])
        assert len(result["revenue"]) == 5

    def test_capex_not_negated(self):
        """FMP capex is already positive — no abs() needed."""
        cashflow = [_make_cashflow(2024, capitalExpenditure=15_000_000_000)]
        result = _extract_series_from_fmp([], [], cashflow)
        assert result["capex"][0]["value"] == 15_000_000_000


# ---------------------------------------------------------------------------
# extract_fmp_fundamentals_near_date
# ---------------------------------------------------------------------------

class TestExtractFmpFundamentalsNearDate:
    def _make_financials(self, years):
        return {
            "income": [_make_income(y) for y in years],
            "balance": [_make_balance(y) for y in years],
            "cashflow": [_make_cashflow(y) for y in years],
        }

    def test_basic_ratio_extraction(self):
        financials = self._make_financials([2024, 2023, 2022])
        result = extract_fmp_fundamentals_near_date(financials, date(2025, 3, 1))

        assert "revenue" in result
        assert "net_margin" in result
        assert "roe" in result
        assert "debt_equity" in result
        assert "fcf" in result
        assert "asset_turnover" in result

    def test_net_margin_computation(self):
        financials = self._make_financials([2024])
        result = extract_fmp_fundamentals_near_date(financials, date(2025, 3, 1))
        # net_income / revenue = 100B / 400B = 0.25
        assert result["net_margin"] == 0.25

    def test_roe_computation(self):
        financials = self._make_financials([2024])
        result = extract_fmp_fundamentals_near_date(financials, date(2025, 3, 1))
        # net_income / equity = 100B / 100B = 1.0
        assert result["roe"] == 1.0

    def test_debt_equity_computation(self):
        financials = self._make_financials([2024])
        result = extract_fmp_fundamentals_near_date(financials, date(2025, 3, 1))
        # total_liabilities / equity = 250B / 100B = 2.5
        assert result["debt_equity"] == 2.5

    def test_fcf_computation(self):
        financials = self._make_financials([2024])
        result = extract_fmp_fundamentals_near_date(financials, date(2025, 3, 1))
        # operating_cf - capex = 110B - 10B = 100B
        assert result["fcf"] == 100_000_000_000

    def test_asset_turnover_computation(self):
        financials = self._make_financials([2024])
        result = extract_fmp_fundamentals_near_date(financials, date(2025, 3, 1))
        # revenue / total_assets = 400B / 350B ≈ 1.1429
        assert result["asset_turnover"] == pytest.approx(1.1429, abs=0.001)

    def test_nearest_date_selection(self):
        """Should pick the closest fiscal year not after target_date."""
        financials = self._make_financials([2024, 2023, 2022])
        # Target is mid-2023 — should pick 2022 (Dec 31) not 2023 (Dec 31)
        result = extract_fmp_fundamentals_near_date(financials, date(2023, 6, 15))
        assert result["_fiscal_date"] == "2022-12-31"

    def test_exact_date_match(self):
        financials = self._make_financials([2024])
        result = extract_fmp_fundamentals_near_date(financials, date(2024, 12, 31))
        assert result["_fiscal_date"] == "2024-12-31"

    def test_no_data_returns_empty(self):
        result = extract_fmp_fundamentals_near_date(
            {"income": [], "balance": [], "cashflow": []},
            date(2025, 1, 1),
        )
        assert result == {}

    def test_no_income_returns_empty(self):
        """If no income statement, return empty (income is required for ratios)."""
        result = extract_fmp_fundamentals_near_date(
            {"income": [], "balance": [_make_balance(2024)], "cashflow": []},
            date(2025, 1, 1),
        )
        assert result == {}

    def test_fiscal_gap_tracking(self):
        financials = self._make_financials([2020])
        result = extract_fmp_fundamentals_near_date(financials, date(2025, 1, 1))
        assert result["_fiscal_gap_days"] > 365 * 4

    def test_all_data_after_target_returns_empty(self):
        """If all fiscal dates are after target, no match."""
        financials = self._make_financials([2025, 2024])
        result = extract_fmp_fundamentals_near_date(financials, date(2023, 6, 1))
        assert result == {}

    def test_partial_statements_still_works(self):
        """If only income is available, still computes what it can."""
        financials = {
            "income": [_make_income(2024)],
            "balance": [],
            "cashflow": [],
        }
        result = extract_fmp_fundamentals_near_date(financials, date(2025, 1, 1))
        assert "revenue" in result
        # No balance/cashflow ratios
        assert "roe" not in result
        assert "fcf" not in result
