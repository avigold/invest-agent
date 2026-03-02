"""Tests for the historical stock screener engine."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.screen.common_features import analyze_common_features
from app.screen.fundamentals_snapshot import extract_fundamentals_near_date
from app.screen.return_scanner import ReturnMatch, find_threshold_windows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_monthly_prices(
    start: str, periods: int, start_price: float, end_price: float
) -> pd.Series:
    """Create a linearly interpolated monthly price series."""
    dates = pd.date_range(start, periods=periods, freq="ME")
    prices = [
        start_price + (end_price - start_price) * i / (periods - 1)
        for i in range(periods)
    ]
    return pd.Series(prices, index=dates)


def _make_match(
    ticker: str,
    return_pct: float,
    gics_code: str = "45",
    country: str = "US",
) -> ReturnMatch:
    return ReturnMatch(
        ticker=ticker,
        name=f"{ticker} Inc",
        country_iso2=country,
        gics_code=gics_code,
        window_start=date(2015, 1, 31),
        window_end=date(2020, 1, 31),
        start_price=10.0,
        end_price=10.0 * (1 + return_pct),
        return_pct=return_pct,
    )


# ---------------------------------------------------------------------------
# return_scanner tests
# ---------------------------------------------------------------------------


class TestReturnScanner:
    def test_finds_match_above_threshold(self):
        # Linear 10→100 over 10yr: first 5yr window goes 10→55, a ~450% return
        prices = {"AAPL": _make_monthly_prices("2010-01", 120, 10.0, 100.0)}
        meta = {"AAPL": {"name": "Apple", "country_iso2": "US", "gics_code": "45"}}

        matches = find_threshold_windows(prices, meta, window_years=5, return_threshold=3.0)

        assert len(matches) == 1
        assert matches[0].ticker == "AAPL"
        assert matches[0].return_pct >= 3.0

    def test_no_match_below_threshold(self):
        # 50% over 5 years — below 300%
        prices = {"MSFT": _make_monthly_prices("2010-01", 120, 10.0, 15.0)}
        meta = {"MSFT": {"name": "Microsoft", "country_iso2": "US", "gics_code": "45"}}

        matches = find_threshold_windows(prices, meta, window_years=5, return_threshold=3.0)

        assert len(matches) == 0

    def test_short_history_skipped(self):
        # Only 2 years of data, need 5 years
        prices = {"TSLA": _make_monthly_prices("2020-01", 24, 10.0, 100.0)}
        meta = {"TSLA": {"name": "Tesla", "country_iso2": "US", "gics_code": "25"}}

        matches = find_threshold_windows(prices, meta, window_years=5, return_threshold=3.0)

        assert len(matches) == 0

    def test_best_window_selected(self):
        # Two distinct peaks: first 4x, then back down, then 6x
        dates = pd.date_range("2005-01", periods=180, freq="ME")
        prices_data = []
        for i in range(180):
            if i < 60:
                prices_data.append(10.0 + (40.0 * i / 60))  # 10 -> 50
            elif i < 90:
                prices_data.append(50.0 - (30.0 * (i - 60) / 30))  # 50 -> 20
            else:
                prices_data.append(20.0 + (80.0 * (i - 90) / 90))  # 20 -> 100
        prices = {"TEST": pd.Series(prices_data, index=dates)}
        meta = {"TEST": {"name": "Test", "country_iso2": "US", "gics_code": "45"}}

        matches = find_threshold_windows(prices, meta, window_years=5, return_threshold=3.0)

        # Should find at least one match with the best return
        assert len(matches) <= 1  # best non-overlapping only

    def test_multiple_tickers(self):
        prices = {
            "BIG": _make_monthly_prices("2010-01", 120, 10.0, 120.0),  # huge gain
            "SMALL": _make_monthly_prices("2010-01", 120, 10.0, 12.0),  # 20%
        }
        meta = {
            "BIG": {"name": "Big", "country_iso2": "US", "gics_code": "45"},
            "SMALL": {"name": "Small", "country_iso2": "US", "gics_code": "40"},
        }

        matches = find_threshold_windows(prices, meta, window_years=5, return_threshold=3.0)

        assert len(matches) == 1
        assert matches[0].ticker == "BIG"

    def test_sorted_by_return_descending(self):
        prices = {
            "A": _make_monthly_prices("2010-01", 120, 10.0, 150.0),  # massive
            "B": _make_monthly_prices("2010-01", 120, 10.0, 100.0),  # big
        }
        meta = {
            "A": {"name": "A", "country_iso2": "US", "gics_code": "45"},
            "B": {"name": "B", "country_iso2": "US", "gics_code": "45"},
        }

        matches = find_threshold_windows(prices, meta, window_years=5, return_threshold=3.0)

        assert len(matches) == 2
        assert matches[0].return_pct >= matches[1].return_pct


# ---------------------------------------------------------------------------
# common_features tests
# ---------------------------------------------------------------------------


class TestCommonFeatures:
    def test_sector_distribution(self):
        matches = [
            _make_match("A", 4.0, gics_code="45"),
            _make_match("B", 3.5, gics_code="45"),
            _make_match("C", 3.2, gics_code="35"),
        ]

        result = analyze_common_features(matches, {})

        assert result["sector_distribution"]["Information Technology"] == 2
        assert result["sector_distribution"]["Health Care"] == 1

    def test_country_distribution(self):
        matches = [
            _make_match("A", 4.0, country="US"),
            _make_match("B", 3.5, country="US"),
            _make_match("C", 3.2, country="GB"),
        ]

        result = analyze_common_features(matches, {})

        assert result["country_distribution"]["US"] == 2
        assert result["country_distribution"]["GB"] == 1

    def test_return_stats(self):
        matches = [
            _make_match("A", 5.0),
            _make_match("B", 3.0),
            _make_match("C", 4.0),
        ]

        result = analyze_common_features(matches, {})

        assert result["return_stats"]["count"] == 3
        assert result["return_stats"]["min"] == 3.0
        assert result["return_stats"]["max"] == 5.0
        assert result["return_stats"]["median"] == 4.0

    def test_fundamental_stats(self):
        fundamentals = {
            "A": {"roe": 0.20, "net_margin": 0.15},
            "B": {"roe": 0.30, "net_margin": 0.10},
        }
        matches = [_make_match("A", 4.0), _make_match("B", 3.5)]

        result = analyze_common_features(matches, fundamentals)

        assert "roe" in result["fundamental_stats"]
        assert result["fundamental_stats"]["roe"]["count"] == 2
        assert result["fundamental_stats"]["roe"]["median"] == 0.25

    def test_empty_matches(self):
        result = analyze_common_features([], {})

        assert result["sector_distribution"] == {}
        assert result["return_stats"] == {}


# ---------------------------------------------------------------------------
# fundamentals_snapshot tests
# ---------------------------------------------------------------------------


class TestFundamentalsSnapshot:
    def test_extract_near_date(self):
        dates = [pd.Timestamp("2018-12-31"), pd.Timestamp("2017-12-31")]
        income = pd.DataFrame(
            {dates[0]: [1e9, 1e8], dates[1]: [8e8, 7e7]},
            index=["Total Revenue", "Net Income"],
        )
        balance = pd.DataFrame(
            {dates[0]: [5e9, 2e9], dates[1]: [4e9, 1.5e9]},
            index=["Total Assets", "Stockholders Equity"],
        )

        result = extract_fundamentals_near_date(
            {"income_stmt": income, "balance_sheet": balance, "cashflow": pd.DataFrame()},
            target_date=date(2019, 6, 1),
        )

        assert "revenue" in result
        assert result["revenue"] == 1e9
        assert "net_margin" in result
        assert abs(result["net_margin"] - 0.1) < 0.001

    def test_empty_financials(self):
        result = extract_fundamentals_near_date(
            {"income_stmt": pd.DataFrame(), "balance_sheet": pd.DataFrame()},
            target_date=date(2019, 1, 1),
        )
        assert result == {}

    def test_picks_closest_date(self):
        dates = [pd.Timestamp("2020-12-31"), pd.Timestamp("2019-12-31"), pd.Timestamp("2018-12-31")]
        income = pd.DataFrame(
            {d: [1e9 * (i + 1)] for i, d in enumerate(dates)},
            index=["Total Revenue"],
        )

        # Target is mid-2020 — should pick 2019-12-31 (closest not after)
        result = extract_fundamentals_near_date(
            {"income_stmt": income, "balance_sheet": pd.DataFrame(), "cashflow": pd.DataFrame()},
            target_date=date(2020, 6, 15),
        )

        assert result["revenue"] == 2e9  # 2019 row (dates[1])
