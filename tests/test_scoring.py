"""Tests for the country scoring engine."""
from __future__ import annotations

import pytest

from app.score.country import (
    compute_1y_return,
    compute_max_drawdown,
    compute_ma_spread,
    percentile_rank,
    _compute_macro_subscores,
    _compute_market_subscores,
)


# ---------------------------------------------------------------------------
# percentile_rank
# ---------------------------------------------------------------------------

class TestPercentileRank:
    def test_ascending_3_values(self):
        # higher_is_better=True: highest value gets rank 1.0
        values = [10.0, 30.0, 20.0]
        ranks = percentile_rank(values, higher_is_better=True)
        assert ranks[0] == 0.0  # 10 = worst
        assert ranks[1] == 1.0  # 30 = best
        assert ranks[2] == 0.5  # 20 = middle

    def test_descending(self):
        # higher_is_better=False: lowest value gets rank 1.0
        values = [10.0, 30.0, 20.0]
        ranks = percentile_rank(values, higher_is_better=False)
        assert ranks[0] == 1.0  # 10 = best (lowest)
        assert ranks[1] == 0.0  # 30 = worst (highest)
        assert ranks[2] == 0.5  # 20 = middle

    def test_ties(self):
        values = [10.0, 10.0, 20.0]
        ranks = percentile_rank(values, higher_is_better=True)
        # Tied values (10, 10) share average of ranks 1 and 2 = 1.5
        # Normalized: (1.5 - 1) / (3 - 1) = 0.25
        assert ranks[0] == ranks[1]
        assert ranks[0] == 0.25
        assert ranks[2] == 1.0  # 20 = best

    def test_none_values(self):
        values = [10.0, None, 20.0]
        ranks = percentile_rank(values, higher_is_better=True)
        assert ranks[1] == 0.5  # None gets median

    def test_all_none(self):
        values = [None, None, None]
        ranks = percentile_rank(values, higher_is_better=True)
        assert all(r == 0.5 for r in ranks)

    def test_single_value(self):
        values = [42.0]
        ranks = percentile_rank(values, higher_is_better=True)
        assert ranks[0] == 0.5

    def test_empty(self):
        assert percentile_rank([]) == []


# ---------------------------------------------------------------------------
# Market metrics
# ---------------------------------------------------------------------------

class TestMarketMetrics:
    def _make_prices(self, closes: list[float]) -> list[dict]:
        return [{"date": f"2024-01-{i+1:02d}", "close": c} for i, c in enumerate(closes)]

    def test_1y_return(self):
        # 252 days: start=100, end=120 → 20%
        prices = self._make_prices([100.0] + [100.0] * 250 + [120.0])
        ret = compute_1y_return(prices)
        assert ret == pytest.approx(0.20)

    def test_1y_return_short_series(self):
        prices = self._make_prices([100.0])
        assert compute_1y_return(prices) is None

    def test_max_drawdown(self):
        # Peak at 100, trough at 80 → -20%
        prices = self._make_prices([100.0, 80.0, 90.0])
        dd = compute_max_drawdown(prices)
        assert dd == pytest.approx(-0.20)

    def test_max_drawdown_no_decline(self):
        prices = self._make_prices([100.0, 110.0, 120.0])
        dd = compute_max_drawdown(prices)
        assert dd == 0.0

    def test_ma_spread(self):
        # 200 prices all at 100, then current at 110 → 10% spread
        prices = self._make_prices([100.0] * 200 + [110.0])
        # SMA_200 covers last 200 prices = (100*199 + 110) / 200 = 100.05
        # Actually need to recalculate: last 200 entries = [100]*199 + [110]
        # SMA = (199*100 + 110) / 200 = 100.05
        spread = compute_ma_spread(prices, window=200)
        expected_sma = (199 * 100 + 110) / 200
        expected = (110 / expected_sma) - 1
        assert spread == pytest.approx(expected)

    def test_ma_spread_too_short(self):
        prices = self._make_prices([100.0] * 10)
        assert compute_ma_spread(prices, window=200) is None


# ---------------------------------------------------------------------------
# Macro subscores
# ---------------------------------------------------------------------------

class TestMacroSubscores:
    def test_basic_scoring(self):
        macro_data = {
            "US": {"gdp_growth": 3.0, "inflation": 2.0, "unemployment": 4.0, "govt_debt_gdp": 120.0, "current_account_gdp": -3.0, "fdi_gdp": 1.5, "reserves": 50.0},
            "GB": {"gdp_growth": 1.0, "inflation": 5.0, "unemployment": 5.0, "govt_debt_gdp": 100.0, "current_account_gdp": -4.0, "fdi_gdp": 2.0, "reserves": 40.0},
            "JP": {"gdp_growth": 2.0, "inflation": 1.0, "unemployment": 3.0, "govt_debt_gdp": 250.0, "current_account_gdp": 3.0, "fdi_gdp": 0.5, "reserves": 100.0},
        }

        scores = _compute_macro_subscores(macro_data)

        # All 3 countries should have scores
        assert len(scores) == 3
        # All scores should be 0-100
        for iso, s in scores.items():
            assert 0 <= s <= 100, f"{iso} score {s} out of range"

    def test_determinism(self):
        """Same inputs must produce same outputs."""
        macro_data = {
            "US": {"gdp_growth": 3.0, "inflation": 2.0, "unemployment": 4.0, "govt_debt_gdp": 120.0, "current_account_gdp": -3.0, "fdi_gdp": 1.5, "reserves": 50.0},
            "GB": {"gdp_growth": 1.0, "inflation": 5.0, "unemployment": 5.0, "govt_debt_gdp": 100.0, "current_account_gdp": -4.0, "fdi_gdp": 2.0, "reserves": 40.0},
        }

        scores1 = _compute_macro_subscores(macro_data)
        scores2 = _compute_macro_subscores(macro_data)
        assert scores1 == scores2


# ---------------------------------------------------------------------------
# Market subscores
# ---------------------------------------------------------------------------

class TestMarketSubscores:
    def _make_prices(self, closes: list[float]) -> list[dict]:
        return [{"date": f"2024-01-{i+1:02d}", "close": c} for i, c in enumerate(closes)]

    def test_basic_market_scoring(self):
        prices = {
            "US": self._make_prices([100.0] * 251 + [120.0]),  # 20% return
            "GB": self._make_prices([100.0] * 251 + [110.0]),  # 10% return
            "JP": self._make_prices([100.0] * 251 + [90.0]),   # -10% return
        }

        scores = _compute_market_subscores(prices)
        assert len(scores) == 3
        # US should score highest (best return, no drawdown)
        assert scores["US"] > scores["JP"]

    def test_empty_prices(self):
        scores = _compute_market_subscores({})
        assert scores == {}
