"""Tests for forward_scanner — fixed forward return observations."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.screen.forward_scanner import (
    Observation,
    _max_drawdown,
    _trailing_ma_spread,
    _trailing_max_drawdown,
    _trailing_momentum,
    _trailing_volatility,
    generate_observations,
)


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


def _make_v_shaped_prices(
    start: str,
    periods: int,
    start_price: float,
    trough_price: float,
    end_price: float,
    trough_at: int | None = None,
) -> pd.Series:
    """Create a V-shaped price series: decline then recovery."""
    dates = pd.date_range(start, periods=periods, freq="ME")
    trough_idx = trough_at or periods // 2
    prices = []
    for i in range(periods):
        if i <= trough_idx:
            p = start_price + (trough_price - start_price) * i / trough_idx
        else:
            p = trough_price + (end_price - trough_price) * (i - trough_idx) / (
                periods - 1 - trough_idx
            )
        prices.append(p)
    return pd.Series(prices, index=dates)


# ---------------------------------------------------------------------------
# _max_drawdown
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    def test_no_drawdown(self):
        # Monotonically increasing
        s = pd.Series([10, 12, 14, 16, 18])
        assert _max_drawdown(s) == 0.0

    def test_simple_drawdown(self):
        # Peak at 20, drops to 10 = -50%
        s = pd.Series([10, 20, 10, 15])
        assert abs(_max_drawdown(s) - (-0.5)) < 0.01

    def test_catastrophic_drawdown(self):
        # Peak at 100, drops to 5 = -95%
        s = pd.Series([50, 100, 5, 10])
        assert _max_drawdown(s) < -0.90


# ---------------------------------------------------------------------------
# Trailing features
# ---------------------------------------------------------------------------


class TestTrailingFeatures:
    def test_momentum_12m(self):
        # 10 -> 20 over 13 months = 100% return
        s = _make_monthly_prices("2020-01", 13, 10.0, 20.0)
        result = _trailing_momentum(s, 12)
        assert result is not None
        assert abs(result - 1.0) < 0.01

    def test_momentum_insufficient_data(self):
        s = _make_monthly_prices("2020-01", 6, 10.0, 15.0)
        assert _trailing_momentum(s, 12) is None

    def test_volatility_positive(self):
        # Any non-flat series should have positive volatility
        s = _make_monthly_prices("2020-01", 24, 10.0, 30.0)
        result = _trailing_volatility(s, 12)
        assert result is not None
        assert result > 0

    def test_max_drawdown_trailing(self):
        # Place trough at month 18 so trailing 12 months captures the decline
        s = _make_v_shaped_prices("2020-01", 24, 100.0, 50.0, 80.0, trough_at=18)
        result = _trailing_max_drawdown(s, 12)
        assert result is not None
        assert result < -0.20

    def test_ma_spread_above(self):
        # Price rising — should be above MA
        s = _make_monthly_prices("2020-01", 20, 10.0, 30.0)
        result = _trailing_ma_spread(s, 10)
        assert result is not None
        assert result > 0


# ---------------------------------------------------------------------------
# generate_observations
# ---------------------------------------------------------------------------


class TestGenerateObservations:
    def test_basic_observations(self):
        # 10 years of data, 5-year forward window → observations at years 0-4
        prices = {"AAPL": _make_monthly_prices("2010-01", 120, 10.0, 100.0)}
        meta = {"AAPL": {"name": "Apple", "country_iso2": "US", "gics_code": "45"}}

        obs = generate_observations(
            prices, meta, window_years=5, return_threshold=3.0
        )

        # Should have several observations (roughly one per year for first 5 years)
        assert len(obs) > 0
        assert all(o.ticker == "AAPL" for o in obs)

    def test_labels_winners(self):
        # Huge gain: 10 -> 200. Any 5-year window from early on should be a winner.
        prices = {"BIG": _make_monthly_prices("2010-01", 120, 10.0, 200.0)}
        meta = {"BIG": {"name": "Big", "country_iso2": "US", "gics_code": "45"}}

        obs = generate_observations(
            prices, meta, window_years=5, return_threshold=3.0
        )

        winners = [o for o in obs if o.label == "winner"]
        assert len(winners) > 0

    def test_labels_catastrophe(self):
        # Crash: 100 -> 5 (95% loss) then stays low
        prices = {"CRASH": _make_v_shaped_prices("2010-01", 120, 100.0, 5.0, 10.0)}
        meta = {"CRASH": {"name": "Crash Co", "country_iso2": "US", "gics_code": "40"}}

        obs = generate_observations(
            prices, meta, window_years=5, return_threshold=3.0,
            catastrophe_threshold=-0.80,
        )

        catastrophes = [o for o in obs if o.label == "catastrophe"]
        assert len(catastrophes) > 0

    def test_no_winners_in_flat_market(self):
        # Flat: 50 -> 55 over 10 years
        prices = {"FLAT": _make_monthly_prices("2010-01", 120, 50.0, 55.0)}
        meta = {"FLAT": {"name": "Flat", "country_iso2": "US", "gics_code": "55"}}

        obs = generate_observations(
            prices, meta, window_years=5, return_threshold=3.0
        )

        winners = [o for o in obs if o.label == "winner"]
        assert len(winners) == 0
        # But should still have normal observations
        assert len(obs) > 0

    def test_short_history_produces_no_observations(self):
        # Only 3 years of data, need 5 years forward
        prices = {"SHORT": _make_monthly_prices("2020-01", 36, 10.0, 20.0)}
        meta = {"SHORT": {"name": "Short", "country_iso2": "US", "gics_code": "45"}}

        obs = generate_observations(
            prices, meta, window_years=5, return_threshold=3.0
        )
        assert len(obs) == 0

    def test_trailing_features_populated(self):
        prices = {"TEST": _make_monthly_prices("2008-01", 180, 10.0, 80.0)}
        meta = {"TEST": {"name": "Test", "country_iso2": "US", "gics_code": "45"}}

        obs = generate_observations(
            prices, meta, window_years=5, return_threshold=3.0
        )

        # Observations after the first year should have trailing features
        later_obs = [o for o in obs if o.momentum_12m is not None]
        assert len(later_obs) > 0
        for o in later_obs:
            assert o.volatility_12m is not None
            assert o.ma_spread is not None

    def test_annual_interval(self):
        # 15 years of data, 5-year forward → up to 10 observation points
        prices = {"LONG": _make_monthly_prices("2005-01", 180, 10.0, 50.0)}
        meta = {"LONG": {"name": "Long", "country_iso2": "US", "gics_code": "45"}}

        obs = generate_observations(
            prices, meta, window_years=5, return_threshold=3.0,
            observation_interval_months=12,
        )

        # Should have roughly (180 - 60) / 12 = 10 observations
        assert 8 <= len(obs) <= 12

    def test_multiple_tickers(self):
        prices = {
            "A": _make_monthly_prices("2010-01", 120, 10.0, 200.0),
            "B": _make_monthly_prices("2010-01", 120, 50.0, 55.0),
        }
        meta = {
            "A": {"name": "A Corp", "country_iso2": "US", "gics_code": "45"},
            "B": {"name": "B Corp", "country_iso2": "US", "gics_code": "55"},
        }

        obs = generate_observations(
            prices, meta, window_years=5, return_threshold=3.0
        )

        tickers = {o.ticker for o in obs}
        assert "A" in tickers
        assert "B" in tickers

    def test_to_dict_serialization(self):
        prices = {"TEST": _make_monthly_prices("2010-01", 120, 10.0, 100.0)}
        meta = {"TEST": {"name": "Test", "country_iso2": "US", "gics_code": "45"}}

        obs = generate_observations(
            prices, meta, window_years=5, return_threshold=3.0
        )

        assert len(obs) > 0
        d = obs[0].to_dict()
        assert isinstance(d, dict)
        assert "ticker" in d
        assert "forward_return" in d
        assert "label" in d
        assert "momentum_12m" in d
