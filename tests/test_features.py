"""Tests for app.predict.features — point-in-time feature computation."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.predict.features import (
    ALL_FEATURES,
    CROSS_SECTIONAL_FEATURES,
    FUNDAMENTAL_FEATURES,
    PRICE_FEATURES,
    add_cross_sectional_ranks,
    compute_fundamental_features,
    compute_price_features,
)


def _make_monthly(values: list[float], start: str = "2020-01-31") -> pd.Series:
    """Create a monthly price series from values."""
    dates = pd.date_range(start, periods=len(values), freq="ME")
    return pd.Series(values, index=dates)


class TestMomentum:
    def test_momentum_3m(self):
        # 4 months of data: 100, 110, 120, 130
        prices = _make_monthly([100, 110, 120, 130])
        result = compute_price_features(prices)
        assert result["momentum_3m"] == pytest.approx(0.30, abs=0.01)

    def test_momentum_6m(self):
        prices = _make_monthly([100, 105, 110, 115, 120, 125, 150])
        result = compute_price_features(prices)
        assert result["momentum_6m"] == pytest.approx(0.50, abs=0.01)

    def test_momentum_12m(self):
        values = [100] + [100] * 11 + [200]  # flat then double
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["momentum_12m"] == pytest.approx(1.0, abs=0.01)

    def test_momentum_24m(self):
        values = [100] + [100] * 23 + [400]  # 4x over 24 months
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["momentum_24m"] == pytest.approx(3.0, abs=0.01)

    def test_momentum_insufficient_data(self):
        prices = _make_monthly([100, 110])  # only 2 months
        result = compute_price_features(prices)
        assert result["momentum_3m"] is None
        assert result["momentum_12m"] is None
        assert result["momentum_24m"] is None

    def test_momentum_zero_start_price(self):
        prices = _make_monthly([0, 100, 200, 300])
        result = compute_price_features(prices)
        # 3m momentum starts at 0 → None
        assert result["momentum_3m"] is None


class TestMomentumAcceleration:
    def test_acceleration_positive(self):
        # Accelerating: slow then fast
        # Need 13+ months: first 6m slow, next 6m fast
        values = [100, 102, 104, 106, 108, 110, 112, 118, 126, 136, 148, 162, 180]
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["momentum_accel"] is not None
        # Recent 6m is stronger than prior 6m → positive
        assert result["momentum_accel"] > 0

    def test_acceleration_insufficient_data(self):
        prices = _make_monthly([100, 110, 120, 130, 140])
        result = compute_price_features(prices)
        assert result["momentum_accel"] is None


class TestRelativeStrength:
    def test_relative_strength_outperformance(self):
        # Stock goes up 50%, index goes up 10%
        stock = _make_monthly([100] + [100] * 11 + [150])
        index = _make_monthly([100] + [100] * 11 + [110])
        result = compute_price_features(stock, index_monthly=index)
        # 0.50 - 0.10 = 0.40
        assert result["relative_strength_12m"] == pytest.approx(0.40, abs=0.01)

    def test_relative_strength_underperformance(self):
        stock = _make_monthly([100] + [100] * 11 + [110])
        index = _make_monthly([100] + [100] * 11 + [150])
        result = compute_price_features(stock, index_monthly=index)
        assert result["relative_strength_12m"] == pytest.approx(-0.40, abs=0.01)

    def test_relative_strength_no_index(self):
        stock = _make_monthly([100] + [100] * 11 + [150])
        result = compute_price_features(stock)
        assert result["relative_strength_12m"] is None


class TestVolatility:
    def test_volatility_6m(self):
        # Alternating returns create measurable volatility
        values = [100, 110, 100, 110, 100, 110, 100]
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["volatility_6m"] is not None
        assert result["volatility_6m"] > 0

    def test_volatility_12m(self):
        values = [100] + [100 + i * 2 for i in range(12)]  # steady climb
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["volatility_12m"] is not None
        assert result["volatility_12m"] >= 0

    def test_vol_trend_expanding(self):
        # Low vol first 6m, high vol last 6m → vol_trend > 1
        values = [100, 101, 102, 103, 104, 105, 106,  # stable first half
                  116, 96, 126, 86, 136, 76]  # wild second half
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        if result["vol_trend"] is not None:
            assert result["vol_trend"] > 1.0

    def test_volatility_insufficient_data(self):
        prices = _make_monthly([100, 110])
        result = compute_price_features(prices)
        assert result["volatility_6m"] is None
        assert result["volatility_12m"] is None


class TestDrawdown:
    def test_max_dd_12m(self):
        # Drop 50% then recover
        values = [100, 100, 100, 100, 100, 100, 100, 50, 60, 70, 80, 90, 100]
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["max_dd_12m"] is not None
        assert result["max_dd_12m"] == pytest.approx(-0.50, abs=0.01)

    def test_max_dd_24m(self):
        values = [100] + [100] * 12 + [50] + [60] * 11  # drop at month 13
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["max_dd_24m"] is not None
        assert result["max_dd_24m"] == pytest.approx(-0.50, abs=0.01)

    def test_no_drawdown(self):
        values = list(range(100, 126))  # monotonic increase
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["max_dd_12m"] == pytest.approx(0.0, abs=0.01)


class TestMASpread:
    def test_ma_spread_above(self):
        # Price well above MA
        values = list(range(100, 121))  # 21 months of steady increase
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["ma_spread_10"] is not None
        assert result["ma_spread_10"] > 0
        assert result["ma_spread_20"] is not None
        assert result["ma_spread_20"] > 0

    def test_ma_spread_below(self):
        # Sharp decline — price below MA
        values = list(range(200, 179, -1))  # decreasing
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["ma_spread_10"] is not None
        assert result["ma_spread_10"] < 0


class TestPriceRange:
    def test_price_range(self):
        # Low of 80, high of 120
        values = [100, 80, 90, 100, 110, 120, 110, 100, 90, 100, 110, 100, 105]
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["price_range_12m"] is not None
        # (120 - 80) / 80 = 0.50
        assert result["price_range_12m"] == pytest.approx(0.50, abs=0.01)


class TestUpMonthsRatio:
    def test_all_up(self):
        values = [100 + i * 5 for i in range(14)]  # all positive returns
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["up_months_ratio_12m"] == pytest.approx(1.0, abs=0.01)

    def test_mixed(self):
        values = [100, 110, 100, 110, 100, 110, 100, 110, 100, 110, 100, 110, 100]
        prices = _make_monthly(values)
        result = compute_price_features(prices)
        assert result["up_months_ratio_12m"] is not None
        assert result["up_months_ratio_12m"] == pytest.approx(0.50, abs=0.01)


class TestFundamentalFeatures:
    def test_all_present(self):
        fundas = {
            "roe": 0.25,
            "net_margin": 0.15,
            "debt_equity": 0.5,
            "revenue_growth": 0.30,
            "fcf_yield": 0.05,
        }
        result = compute_fundamental_features(fundas)
        assert result["roe"] == 0.25
        assert result["net_margin"] == 0.15
        assert result["debt_equity"] == 0.5
        assert result["revenue_growth"] == 0.30
        assert result["fcf_yield"] == 0.05

    def test_partial(self):
        fundas = {"roe": 0.20}
        result = compute_fundamental_features(fundas)
        assert result["roe"] == 0.20
        assert result["net_margin"] is None
        assert result["debt_equity"] is None

    def test_empty(self):
        result = compute_fundamental_features({})
        assert all(v is None for v in result.values())


class TestCrossSectionalRanks:
    def test_basic_ranking(self):
        rows = [
            {"momentum_12m": 0.10, "volatility_12m": 0.30},
            {"momentum_12m": 0.20, "volatility_12m": 0.20},
            {"momentum_12m": 0.30, "volatility_12m": 0.10},
        ]
        add_cross_sectional_ranks(rows)
        # momentum: 0.10 < 0.20 < 0.30 → ranks ~0.17, 0.50, 0.83
        assert rows[0]["momentum_12m_rank"] < rows[1]["momentum_12m_rank"]
        assert rows[1]["momentum_12m_rank"] < rows[2]["momentum_12m_rank"]
        # volatility: opposite ordering
        assert rows[2]["volatility_12m_rank"] < rows[1]["volatility_12m_rank"]
        assert rows[1]["volatility_12m_rank"] < rows[0]["volatility_12m_rank"]

    def test_with_none_values(self):
        rows = [
            {"momentum_12m": 0.10, "volatility_12m": None},
            {"momentum_12m": None, "volatility_12m": 0.20},
            {"momentum_12m": 0.30, "volatility_12m": 0.10},
        ]
        add_cross_sectional_ranks(rows)
        assert rows[0]["momentum_12m_rank"] is not None
        assert rows[1]["momentum_12m_rank"] is None  # was None input
        assert rows[2]["momentum_12m_rank"] is not None
        assert rows[0]["volatility_12m_rank"] is None  # was None input

    def test_all_none(self):
        rows = [
            {"momentum_12m": None, "volatility_12m": None},
            {"momentum_12m": None, "volatility_12m": None},
        ]
        add_cross_sectional_ranks(rows)
        assert rows[0]["momentum_12m_rank"] is None
        assert rows[1]["volatility_12m_rank"] is None

    def test_single_observation(self):
        rows = [{"momentum_12m": 0.15, "volatility_12m": 0.25}]
        add_cross_sectional_ranks(rows)
        # Single item → rank 0.5
        assert rows[0]["momentum_12m_rank"] == pytest.approx(0.5, abs=0.01)


class TestFeatureListConsistency:
    def test_all_features_produced(self):
        """Verify compute_price_features + compute_fundamental_features + ranks
        cover all features in ALL_FEATURES."""
        values = [100 + i for i in range(26)]  # 26 months
        prices = _make_monthly(values)
        index = _make_monthly(values)

        price_feats = compute_price_features(prices, index_monthly=index)
        fund_feats = compute_fundamental_features({
            "roe": 0.1, "net_margin": 0.1, "debt_equity": 0.5,
            "revenue_growth": 0.2, "fcf_yield": 0.03,
        })

        combined = {**price_feats, **fund_feats}
        # Add rank features
        rows = [combined]
        add_cross_sectional_ranks(rows)

        for feat in ALL_FEATURES:
            assert feat in rows[0], f"Missing feature: {feat}"
