"""Tests for walk-forward Parquet model training."""
import tempfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.predict.model import (
    _compute_precision_at_k,
    train_walk_forward_parquet,
    _compute_calibration_buckets,
    TrainedModel,
)
from app.predict.parquet_dataset import ParquetDataset, load_parquet_dataset


# ── Fixtures ───────────────────────────────────────────────────────


def _make_training_parquet(tmp_path: Path, n_per_year: int = 200) -> str:
    """Create a synthetic Parquet with enough data for walk-forward training."""
    rng = np.random.RandomState(42)

    rows = []
    for yr in range(2015, 2025):  # 10 years
        for i in range(n_per_year):
            # Create some signal: higher momentum → more likely winner
            momentum = float(rng.uniform(-0.5, 2.0))
            is_winner = rng.random() < (0.1 + 0.1 * max(momentum, 0))

            row = {
                "fiscal_year": yr,
                "statement_date": f"{yr}-12-31",
                "reported_currency": "USD",
                "ticker": f"T{yr}_{i:04d}",
                "company_name": f"Company {yr}_{i}",
                "country_iso2": rng.choice(["US", "GB", "DE"]),
                "gics_code": rng.choice(["45", "20", "35"]),
                "inc_revenue": float(rng.uniform(100, 10000)),
                "inc_netIncome": float(rng.uniform(-100, 1000)),
                "bal_totalAssets": float(rng.uniform(500, 50000)),
                "cf_freeCashFlow": float(rng.uniform(-500, 5000)),
                "gross_margin": float(rng.uniform(0.1, 0.9)),
                "roe": float(rng.uniform(-0.5, 1.0)),
                "piotroski_f_score": int(rng.randint(0, 10)),
                "momentum_12m": momentum,
                "volatility_12m": float(rng.uniform(0.1, 1.0)),
                "max_dd_12m": float(rng.uniform(-0.8, 0)),
                "relative_strength_12m": None,
                "beta_vs_index": None,
                "fwd_return_3m": float(rng.uniform(-0.3, 0.5)),
                "fwd_return_6m": float(rng.uniform(-0.4, 1.0)),
                "fwd_return_12m": float(rng.uniform(1.0, 5.0)) if is_winner else float(rng.uniform(-0.5, 0.9)),
                "fwd_return_24m": float(rng.uniform(-0.5, 5.0)),
                "fwd_max_dd_12m": float(rng.uniform(-0.8, 0)),
                "fwd_label": "winner" if is_winner else "normal",
                "ctx_company_overall_score": float(rng.uniform(30, 90)),
            }
            rows.append(row)

    table = pa.Table.from_pylist(rows)
    path = str(tmp_path / "train_features.parquet")
    pq.write_table(table, path)
    return path


# ── Precision@K Tests ─────────────────────────────────────────────


class TestPrecisionAtK:
    def test_perfect_ranking(self):
        labels = np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0], dtype=float)
        scores = np.array([0.9, 0.8, 0.7, 0.3, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1])
        result = _compute_precision_at_k(labels, scores, k_values=[3])
        assert result["precision@3"] == pytest.approx(1.0)

    def test_worst_ranking(self):
        labels = np.array([0, 0, 0, 1, 1, 1, 0, 0, 0, 0], dtype=float)
        scores = np.array([0.9, 0.8, 0.7, 0.3, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1])
        result = _compute_precision_at_k(labels, scores, k_values=[3])
        assert result["precision@3"] == pytest.approx(0.0)

    def test_k_larger_than_data(self):
        labels = np.array([1, 0, 1], dtype=float)
        scores = np.array([0.9, 0.5, 0.1])
        result = _compute_precision_at_k(labels, scores, k_values=[10])
        assert "precision@10" not in result  # K > len(labels)

    def test_multiple_k(self):
        labels = np.array([1, 1, 0, 0, 1, 0, 0, 0, 0, 0], dtype=float)
        scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05])
        result = _compute_precision_at_k(labels, scores, k_values=[2, 5])
        assert result["precision@2"] == pytest.approx(1.0)
        assert result["precision@5"] == pytest.approx(3 / 5)


# ── Calibration Tests ─────────────────────────────────────────────


class TestCalibration:
    def test_bucket_count(self):
        labels = np.random.RandomState(42).randint(0, 2, 100).astype(float)
        probs = np.random.RandomState(42).uniform(0, 1, 100)
        buckets = _compute_calibration_buckets(labels, probs, n_buckets=10)
        assert len(buckets) == 10

    def test_all_rows_covered(self):
        labels = np.random.RandomState(42).randint(0, 2, 100).astype(float)
        probs = np.random.RandomState(42).uniform(0, 1, 100)
        buckets = _compute_calibration_buckets(labels, probs, n_buckets=10)
        total = sum(b["count"] for b in buckets)
        assert total == 100


# ── Walk-Forward Training Tests ───────────────────────────────────


class TestTrainWalkForwardParquet:
    @pytest.fixture
    def dataset(self, tmp_path):
        path = _make_training_parquet(tmp_path, n_per_year=200)
        return load_parquet_dataset(path, min_fiscal_year=2015)

    def test_produces_fold_results(self, dataset):
        trained = train_walk_forward_parquet(
            dataset,
            fold_years=[2022, 2023],
            holdout_year=2024,
            num_boost_round=50,
            early_stopping_rounds=10,
        )
        assert len(trained.fold_results) == 2
        assert trained.fold_results[0].year == 2022
        assert trained.fold_results[1].year == 2023

    def test_auc_above_random(self, dataset):
        """With a signal in the data, AUC should be above 0.5."""
        trained = train_walk_forward_parquet(
            dataset,
            fold_years=[2022, 2023],
            holdout_year=2024,
            num_boost_round=50,
            early_stopping_rounds=10,
        )
        # At least one fold should have AUC > 0.5
        aucs = [fr.auc for fr in trained.fold_results]
        assert max(aucs) > 0.5

    def test_feature_importance_populated(self, dataset):
        trained = train_walk_forward_parquet(
            dataset,
            fold_years=[2022],
            holdout_year=2024,
            num_boost_round=50,
            early_stopping_rounds=10,
        )
        assert len(trained.feature_importance) > 0
        total = sum(trained.feature_importance.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_holdout_metrics(self, dataset):
        trained = train_walk_forward_parquet(
            dataset,
            fold_years=[2022, 2023],
            holdout_year=2024,
            num_boost_round=50,
            early_stopping_rounds=10,
        )
        holdout = trained.train_config.get("holdout_metrics", {})
        assert holdout.get("year") == 2024
        assert "auc" in holdout
        assert holdout["n"] > 0

    def test_platt_calibration(self, dataset):
        trained = train_walk_forward_parquet(
            dataset,
            fold_years=[2022, 2023],
            holdout_year=2024,
            num_boost_round=50,
            early_stopping_rounds=10,
        )
        # Platt params should be non-default
        assert trained.platt_a != 0.0 or trained.platt_b != 0.0

    def test_serialize_deserialize(self, dataset):
        trained = train_walk_forward_parquet(
            dataset,
            fold_years=[2022],
            holdout_year=2024,
            num_boost_round=50,
            early_stopping_rounds=10,
        )
        blob = trained.serialize()
        restored = TrainedModel.deserialize(
            blob,
            feature_importance=trained.feature_importance,
            train_config=trained.train_config,
        )
        assert restored.feature_names == trained.feature_names
        assert restored.platt_a == pytest.approx(trained.platt_a)
        assert restored.platt_b == pytest.approx(trained.platt_b)

        # Predictions should match
        X_sample = dataset.X[:10]
        orig_preds = trained.predict_proba(X_sample)
        rest_preds = restored.predict_proba(X_sample)
        np.testing.assert_array_almost_equal(orig_preds, rest_preds)

    def test_model_version(self, dataset):
        trained = train_walk_forward_parquet(
            dataset,
            fold_years=[2022],
            holdout_year=2024,
            num_boost_round=50,
            early_stopping_rounds=10,
        )
        assert trained.train_config["model_version"] == "predictor_v2_parquet"
