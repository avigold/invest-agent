"""Tests for app.predict.parquet_dataset — Parquet loading and preprocessing."""
import tempfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.predict.parquet_dataset import (
    ParquetDataset,
    _EXCLUDE_COLUMNS,
    _IDENTIFIER_COLUMNS,
    _NULL_COLUMNS,
    _TARGET_COLUMNS,
    compute_recency_weights,
    load_parquet_dataset,
)


# ── Fixtures ───────────────────────────────────────────────────────


def _make_parquet(tmp_path: Path, n_rows: int = 100, n_years: int = 5) -> str:
    """Create a synthetic Parquet file mimicking the training export."""
    rng = np.random.RandomState(42)

    tickers = [f"TICK{i}" for i in range(n_rows // n_years)]
    rows = []
    for ticker in tickers:
        for yr in range(2020, 2020 + n_years):
            row = {
                "fiscal_year": yr,
                "statement_date": f"{yr}-12-31",
                "reported_currency": "USD",
                "ticker": ticker,
                "company_name": f"{ticker} Corp",
                "country_iso2": rng.choice(["US", "GB", "DE"]),
                "gics_code": rng.choice(["45", "20", "35"]),
                # A few raw financials
                "inc_revenue": float(rng.uniform(100, 10000)),
                "inc_netIncome": float(rng.uniform(-100, 1000)),
                "bal_totalAssets": float(rng.uniform(500, 50000)),
                "cf_freeCashFlow": float(rng.uniform(-500, 5000)),
                # Derived ratios
                "gross_margin": float(rng.uniform(0.1, 0.9)),
                "roe": float(rng.uniform(-0.5, 1.0)),
                "piotroski_f_score": int(rng.randint(0, 10)),
                # Price features
                "momentum_12m": float(rng.uniform(-0.5, 2.0)),
                "volatility_12m": float(rng.uniform(0.1, 1.0)),
                "max_dd_12m": float(rng.uniform(-0.8, 0)),
                # Always-null columns
                "relative_strength_12m": None,
                "beta_vs_index": None,
                # Forward returns / targets
                "fwd_return_3m": float(rng.uniform(-0.5, 1.0)),
                "fwd_return_6m": float(rng.uniform(-0.5, 2.0)),
                "fwd_return_12m": float(rng.uniform(-0.5, 3.0)),
                "fwd_return_24m": float(rng.uniform(-0.5, 5.0)),
                "fwd_max_dd_12m": float(rng.uniform(-0.8, 0)),
                "fwd_label": rng.choice(["winner", "normal"], p=[0.1, 0.9]),
                # Context
                "ctx_company_overall_score": float(rng.uniform(30, 90)),
            }
            rows.append(row)

    table = pa.Table.from_pylist(rows)
    path = str(tmp_path / "test_features.parquet")
    pq.write_table(table, path)
    return path


# ── Recency Weight Tests ──────────────────────────────────────────


class TestRecencyWeights:
    def test_current_year_weight_is_one(self):
        years = np.array([2023])
        w = compute_recency_weights(years, max_train_year=2023, half_life=7.0)
        assert w[0] == pytest.approx(1.0)

    def test_half_life_decay(self):
        years = np.array([2016])
        w = compute_recency_weights(years, max_train_year=2023, half_life=7.0)
        assert w[0] == pytest.approx(0.5, abs=0.001)

    def test_double_half_life(self):
        years = np.array([2009])
        w = compute_recency_weights(years, max_train_year=2023, half_life=7.0)
        assert w[0] == pytest.approx(0.25, abs=0.001)

    def test_all_weights_positive(self):
        years = np.array([2000, 2005, 2010, 2015, 2020, 2023])
        w = compute_recency_weights(years, max_train_year=2023, half_life=7.0)
        assert np.all(w > 0)

    def test_monotonic_decrease(self):
        years = np.array([2023, 2022, 2021, 2020, 2015, 2010, 2000])
        w = compute_recency_weights(years, max_train_year=2023, half_life=7.0)
        for i in range(len(w) - 1):
            assert w[i] >= w[i + 1]

    def test_different_half_lives(self):
        years = np.array([2018])
        w5 = compute_recency_weights(years, max_train_year=2023, half_life=5.0)
        w10 = compute_recency_weights(years, max_train_year=2023, half_life=10.0)
        # Shorter half-life → more aggressive decay → lower weight
        assert w5[0] < w10[0]


# ── Parquet Dataset Loading Tests ─────────────────────────────────


class TestLoadParquetDataset:
    @pytest.fixture
    def parquet_path(self, tmp_path):
        return _make_parquet(tmp_path, n_rows=100, n_years=5)

    def test_loads_successfully(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020)
        assert isinstance(ds, ParquetDataset)
        assert ds.n_observations > 0
        assert ds.n_features > 0

    def test_identifiers_excluded(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020)
        for col in _IDENTIFIER_COLUMNS:
            assert col not in ds.feature_names

    def test_targets_excluded(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020)
        for col in _TARGET_COLUMNS:
            assert col not in ds.feature_names

    def test_null_columns_excluded(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020)
        for col in _NULL_COLUMNS:
            assert col not in ds.feature_names

    def test_forward_returns_not_in_features(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020)
        fwd_cols = [c for c in ds.feature_names if c.startswith("fwd_")]
        assert len(fwd_cols) == 0

    def test_label_encoding(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020)
        # Labels should be 0 or 1
        assert set(np.unique(ds.y)).issubset({0.0, 1.0})

    def test_fiscal_year_filtering(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2022)
        assert np.all(ds.fiscal_years >= 2022)

    def test_null_label_filtered(self, tmp_path):
        """Rows with fwd_label=None should be excluded."""
        rows = [
            {"fiscal_year": 2023, "ticker": "A", "company_name": "A",
             "country_iso2": "US", "gics_code": "45",
             "statement_date": "2023-12-31", "reported_currency": "USD",
             "inc_revenue": 100.0, "fwd_label": "winner",
             "fwd_return_12m": 1.5, "fwd_return_3m": 0.5,
             "fwd_return_6m": 0.8, "fwd_return_24m": 2.0,
             "fwd_max_dd_12m": -0.1,
             "relative_strength_12m": None, "beta_vs_index": None},
            {"fiscal_year": 2023, "ticker": "B", "company_name": "B",
             "country_iso2": "US", "gics_code": "45",
             "statement_date": "2023-12-31", "reported_currency": "USD",
             "inc_revenue": 200.0, "fwd_label": None,
             "fwd_return_12m": None, "fwd_return_3m": None,
             "fwd_return_6m": None, "fwd_return_24m": None,
             "fwd_max_dd_12m": None,
             "relative_strength_12m": None, "beta_vs_index": None},
        ]
        table = pa.Table.from_pylist(rows)
        path = str(tmp_path / "null_label.parquet")
        pq.write_table(table, path)

        ds = load_parquet_dataset(path, min_fiscal_year=2020)
        assert ds.n_observations == 1  # Only the winner row

    def test_categorical_encoding(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020)
        assert "cat_gics_code" in ds.feature_names
        assert "cat_country_iso2" in ds.feature_names
        assert len(ds.categorical_features) == 2

        # Categorical values should be integers
        gics_idx = ds.feature_names.index("cat_gics_code")
        gics_vals = ds.X[:, gics_idx]
        non_nan = gics_vals[~np.isnan(gics_vals)]
        assert np.all(non_nan == non_nan.astype(int))

    def test_weights_computed(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020, half_life=7.0)
        assert len(ds.weights) == ds.n_observations
        assert np.all(ds.weights > 0)
        assert np.all(ds.weights <= 1.0)

    def test_tickers_preserved(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020)
        assert len(ds.tickers) == ds.n_observations
        assert all(isinstance(t, str) for t in ds.tickers)

    def test_forward_returns_preserved(self, parquet_path):
        ds = load_parquet_dataset(parquet_path, min_fiscal_year=2020)
        assert len(ds.forward_returns) == ds.n_observations
