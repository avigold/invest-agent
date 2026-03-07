"""Tests for app.predict.dataset — feature matrix builder."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.predict.dataset import Dataset, build_dataset
from app.predict.features import ALL_FEATURES
from app.screen.forward_scanner import Observation


def _daily_prices(start: str, months: int, base: float = 100.0, growth: float = 0.001) -> pd.Series:
    """Generate daily prices with slight upward trend."""
    dates = pd.date_range(start, periods=months * 21, freq="B")  # ~21 business days/month
    prices = [base * (1 + growth) ** i for i in range(len(dates))]
    return pd.Series(prices, index=dates)


def _make_obs(
    ticker: str = "AAPL",
    obs_date: date = date(2020, 1, 31),
    forward_return: float = 0.5,
    label: str = "normal",
    fundamentals: dict | None = None,
) -> Observation:
    return Observation(
        ticker=ticker,
        name=f"{ticker} Inc",
        country_iso2="US",
        gics_code="45",
        obs_date=obs_date,
        forward_return=forward_return,
        forward_max_dd=-0.10,
        label=label,
        obs_price=100.0,
        fundamentals=fundamentals or {},
    )


class TestBuildDataset:
    def test_empty_observations(self):
        ds = build_dataset([], {})
        assert ds.n_observations == 0
        assert ds.X.shape == (0, len(ALL_FEATURES))
        assert ds.y.shape == (0,)

    def test_single_observation(self):
        obs = _make_obs(obs_date=date(2020, 6, 30), label="winner", forward_return=4.0)
        prices = {"AAPL": _daily_prices("2017-01-01", 48)}  # 4 years of daily data
        ds = build_dataset([obs], prices)
        assert ds.n_observations == 1
        assert ds.X.shape == (1, len(ALL_FEATURES))
        assert ds.y[0] == 1.0  # winner
        assert ds.meta[0].ticker == "AAPL"
        assert ds.meta[0].label == "winner"

    def test_multiple_observations(self):
        obs_list = [
            _make_obs("AAPL", date(2019, 1, 31), 4.0, "winner"),
            _make_obs("GOOG", date(2019, 1, 31), 0.5, "normal"),
            _make_obs("MSFT", date(2019, 1, 31), -0.9, "catastrophe"),
        ]
        prices = {
            "AAPL": _daily_prices("2016-01-01", 48, base=100),
            "GOOG": _daily_prices("2016-01-01", 48, base=200),
            "MSFT": _daily_prices("2016-01-01", 48, base=150),
        }
        ds = build_dataset(obs_list, prices)
        assert ds.n_observations == 3
        assert ds.n_winners == 1
        assert ds.y.tolist() == [1.0, 0.0, 0.0]

    def test_labels_binary(self):
        """Catastrophe and normal both map to 0."""
        obs_list = [
            _make_obs("A", date(2019, 6, 30), 4.0, "winner"),
            _make_obs("B", date(2019, 6, 30), 0.5, "normal"),
            _make_obs("C", date(2019, 6, 30), -0.9, "catastrophe"),
        ]
        prices = {
            "A": _daily_prices("2016-01-01", 48),
            "B": _daily_prices("2016-01-01", 48),
            "C": _daily_prices("2016-01-01", 48),
        }
        ds = build_dataset(obs_list, prices)
        assert ds.y.tolist() == [1.0, 0.0, 0.0]

    def test_base_rate(self):
        obs_list = [
            _make_obs("A", date(2019, 6, 30), 4.0, "winner"),
            _make_obs("B", date(2019, 6, 30), 0.5, "normal"),
            _make_obs("C", date(2019, 6, 30), 0.3, "normal"),
            _make_obs("D", date(2019, 6, 30), 0.1, "normal"),
        ]
        prices = {t: _daily_prices("2016-01-01", 48) for t in ["A", "B", "C", "D"]}
        ds = build_dataset(obs_list, prices)
        assert ds.base_rate == pytest.approx(0.25, abs=0.01)

    def test_feature_names_match(self):
        ds = build_dataset([], {})
        assert ds.feature_names == list(ALL_FEATURES)

    def test_missing_price_data_skipped(self):
        obs = _make_obs("AAPL", date(2020, 1, 31))
        # No AAPL in prices dict
        ds = build_dataset([obs], {"GOOG": _daily_prices("2016-01-01", 48)})
        assert ds.n_observations == 0

    def test_cross_sectional_ranks_computed(self):
        """Observations at the same date get cross-sectional ranks."""
        obs_list = [
            _make_obs("A", date(2019, 6, 30), 0.5, "normal"),
            _make_obs("B", date(2019, 6, 30), 0.3, "normal"),
        ]
        # A has higher growth → higher momentum
        prices = {
            "A": _daily_prices("2016-01-01", 48, growth=0.003),
            "B": _daily_prices("2016-01-01", 48, growth=0.001),
        }
        ds = build_dataset(obs_list, prices)
        assert ds.n_observations == 2
        # momentum_12m_rank column index
        rank_idx = ds.feature_names.index("momentum_12m_rank")
        # A should have higher rank than B
        assert ds.X[0, rank_idx] > ds.X[1, rank_idx]

    def test_fundamentals_included(self):
        obs = _make_obs(
            "AAPL",
            date(2020, 6, 30),
            fundamentals={"roe": 0.25, "net_margin": 0.15},
        )
        prices = {"AAPL": _daily_prices("2017-01-01", 48)}
        ds = build_dataset([obs], prices)
        roe_idx = ds.feature_names.index("roe")
        nm_idx = ds.feature_names.index("net_margin")
        de_idx = ds.feature_names.index("debt_equity")
        assert ds.X[0, roe_idx] == pytest.approx(0.25)
        assert ds.X[0, nm_idx] == pytest.approx(0.15)
        assert np.isnan(ds.X[0, de_idx])  # not provided → NaN

    def test_index_prices_for_relative_strength(self):
        obs = _make_obs("AAPL", date(2020, 6, 30), label="normal")
        stock = _daily_prices("2017-01-01", 48, growth=0.005)
        index = _daily_prices("2017-01-01", 48, growth=0.001)
        ds = build_dataset([obs], {"AAPL": stock}, index_prices={"US": index})
        rs_idx = ds.feature_names.index("relative_strength_12m")
        # Stock grows faster → positive relative strength
        assert not np.isnan(ds.X[0, rs_idx])
        assert ds.X[0, rs_idx] > 0

    def test_nan_for_sparse_features(self):
        """Features that can't be computed are NaN, not zero."""
        obs = _make_obs("AAPL", date(2018, 7, 31))  # near start of price data
        # Only 6 months of price data before obs → can't compute 12m features
        prices = {"AAPL": _daily_prices("2018-01-01", 8)}
        ds = build_dataset([obs], prices)
        if ds.n_observations > 0:
            mom24_idx = ds.feature_names.index("momentum_24m")
            assert np.isnan(ds.X[0, mom24_idx])


class TestDatasetProperties:
    def test_properties(self):
        ds = Dataset(
            X=np.zeros((5, 3)),
            y=np.array([1, 0, 1, 0, 0], dtype=np.float64),
            feature_names=["a", "b", "c"],
            meta=[],
        )
        assert ds.n_observations == 5
        assert ds.n_features == 3
        assert ds.n_winners == 2
        assert ds.base_rate == pytest.approx(0.4)

    def test_empty_base_rate(self):
        ds = Dataset(
            X=np.empty((0, 3)),
            y=np.empty(0),
            feature_names=["a", "b", "c"],
            meta=[],
        )
        assert ds.base_rate == 0.0
