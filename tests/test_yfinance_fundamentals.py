"""Tests for yfinance financial statements extraction."""
from __future__ import annotations

import pytest

from app.ingest.yfinance_fundamentals import _extract_series_from_financials


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_column_map():
    return {
        "revenue": ["Total Revenue", "Revenue"],
        "net_income": ["Net Income", "Net Income Common Stockholders"],
        "operating_income": ["Operating Income", "EBIT"],
        "eps_diluted": ["Diluted EPS"],
        "total_assets": ["Total Assets"],
        "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liab"],
        "stockholders_equity": ["Stockholders Equity", "Total Stockholders Equity"],
        "cash_from_ops": ["Operating Cash Flow"],
        "capex": ["Capital Expenditure"],
    }


def _make_financials(**overrides):
    """Build a minimal financials dict mimicking yfinance output."""
    base = {
        "income_stmt": {
            "Total Revenue": {"2023-12-31": 100_000.0, "2022-12-31": 90_000.0},
            "Net Income": {"2023-12-31": 20_000.0, "2022-12-31": 18_000.0},
            "Operating Income": {"2023-12-31": 30_000.0},
            "Diluted EPS": {"2023-12-31": 5.50, "2022-12-31": 4.80},
        },
        "balance_sheet": {
            "Total Assets": {"2023-12-31": 500_000.0},
            "Total Liabilities Net Minority Interest": {"2023-12-31": 300_000.0},
            "Stockholders Equity": {"2023-12-31": 200_000.0},
        },
        "cashflow": {
            "Operating Cash Flow": {"2023-12-31": 35_000.0},
            "Capital Expenditure": {"2023-12-31": -10_000.0},  # yfinance reports negative
        },
    }
    for k, v in overrides.items():
        base[k] = v
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExtractSeriesFromFinancials:
    def test_basic_extraction(self):
        financials = _make_financials()
        result = _extract_series_from_financials(financials, _make_column_map())
        assert "revenue" in result
        assert result["revenue"][0]["fiscal_year"] == 2023
        assert result["revenue"][0]["value"] == 100_000.0
        assert result["revenue"][1]["fiscal_year"] == 2022

    def test_all_metrics_extracted(self):
        financials = _make_financials()
        result = _extract_series_from_financials(financials, _make_column_map())
        expected_keys = {
            "revenue", "net_income", "operating_income", "eps_diluted",
            "total_assets", "total_liabilities", "stockholders_equity",
            "cash_from_ops", "capex",
        }
        assert set(result.keys()) == expected_keys

    def test_fallback_column_names(self):
        """When primary column is missing, should use fallback."""
        financials = _make_financials(
            income_stmt={
                "Revenue": {"2023-12-31": 80_000.0},  # fallback, not "Total Revenue"
                "Net Income Common Stockholders": {"2023-12-31": 15_000.0},
            },
        )
        result = _extract_series_from_financials(financials, _make_column_map())
        assert "revenue" in result
        assert result["revenue"][0]["value"] == 80_000.0
        assert "net_income" in result
        assert result["net_income"][0]["value"] == 15_000.0

    def test_capex_sign_normalization(self):
        """CapEx should be normalized to positive (absolute value)."""
        financials = _make_financials()
        result = _extract_series_from_financials(financials, _make_column_map())
        assert "capex" in result
        assert result["capex"][0]["value"] == 10_000.0  # was -10_000.0

    def test_empty_dataframe(self):
        """Should return empty dict when DataFrame is empty."""
        financials = {
            "income_stmt": {},
            "balance_sheet": {},
            "cashflow": {},
        }
        result = _extract_series_from_financials(financials, _make_column_map())
        assert result == {}

    def test_partial_data(self):
        """Should extract what's available and skip what's missing."""
        financials = {
            "income_stmt": {
                "Total Revenue": {"2023-12-31": 50_000.0},
            },
            "balance_sheet": {},
            "cashflow": {},
        }
        result = _extract_series_from_financials(financials, _make_column_map())
        assert "revenue" in result
        assert "total_assets" not in result
        assert "capex" not in result

    def test_sorted_by_year_descending(self):
        financials = _make_financials(
            income_stmt={
                "Total Revenue": {
                    "2021-12-31": 70_000.0,
                    "2023-12-31": 100_000.0,
                    "2022-12-31": 85_000.0,
                },
            }
        )
        result = _extract_series_from_financials(financials, _make_column_map())
        years = [p["fiscal_year"] for p in result["revenue"]]
        assert years == [2023, 2022, 2021]

    def test_capex_already_positive(self):
        """If capex is already positive, abs() should keep it positive."""
        financials = _make_financials(
            cashflow={
                "Capital Expenditure": {"2023-12-31": 10_000.0},
                "Operating Cash Flow": {"2023-12-31": 35_000.0},
            }
        )
        result = _extract_series_from_financials(financials, _make_column_map())
        assert result["capex"][0]["value"] == 10_000.0
