"""Tests for app.predict.model — LightGBM training, Platt scaling, walk-forward CV."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.predict.dataset import Dataset, ObservationMeta
from app.predict.features import ALL_FEATURES
from app.predict.model import (
    TrainedModel,
    _apply_platt,
    _compute_auc,
    platt_scale,
    train_walk_forward,
)


def _make_dataset(n: int = 500, n_pos: int = 50, start_year: int = 2010) -> Dataset:
    """Create a synthetic dataset for testing.

    Generates data where positive examples have slightly higher feature values
    on the first few features, so the model has something to learn.
    """
    rng = np.random.RandomState(42)
    n_features = len(ALL_FEATURES)

    X = rng.randn(n, n_features)
    y = np.zeros(n)
    y[:n_pos] = 1.0
    rng.shuffle(y)

    # Add signal: positive examples have higher values on first 3 features
    for i in range(n):
        if y[i] == 1:
            X[i, :3] += 1.5

    # Assign years spanning start_year to start_year + 10
    years = rng.choice(range(start_year, start_year + 11), size=n)
    meta = [
        ObservationMeta(
            ticker=f"T{i}",
            obs_date=date(int(years[i]), 6, 30),
            forward_return=4.0 if y[i] == 1 else 0.2,
            label="winner" if y[i] == 1 else "normal",
        )
        for i in range(n)
    ]

    return Dataset(
        X=X,
        y=y,
        feature_names=list(ALL_FEATURES),
        meta=meta,
    )


class TestPlattScaling:
    def test_basic_fit(self):
        """Platt scaling should produce reasonable A, B values."""
        rng = np.random.RandomState(42)
        scores = rng.randn(200)
        labels = (scores > 0).astype(float)
        # Add noise: flip ~10% of labels
        flip_mask = rng.rand(200) < 0.1
        labels[flip_mask] = 1 - labels[flip_mask]

        A, B = platt_scale(scores, labels)
        # A should be negative (higher score → higher probability)
        assert A < 0
        assert isinstance(B, float)

    def test_calibrated_monotonic(self):
        """Higher scores should give higher probabilities."""
        scores = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        labels = np.array([0, 0, 1, 1, 1], dtype=float)

        A, B = platt_scale(scores, labels)
        probs = _apply_platt(scores, A, B)

        # Should be monotonically increasing
        for i in range(len(probs) - 1):
            assert probs[i] <= probs[i + 1]

    def test_probabilities_in_range(self):
        """Calibrated probabilities should be between 0 and 1."""
        rng = np.random.RandomState(42)
        scores = rng.randn(100) * 3
        labels = (scores > 0).astype(float)

        A, B = platt_scale(scores, labels)
        probs = _apply_platt(scores, A, B)

        assert np.all(probs >= 0)
        assert np.all(probs <= 1)

    def test_extreme_scores(self):
        """Should handle very large and very small scores."""
        scores = np.array([-100, -10, 0, 10, 100])
        A, B = -1.0, 0.0
        probs = _apply_platt(scores, A, B)
        assert np.all(np.isfinite(probs))
        assert np.all(probs >= 0)
        assert np.all(probs <= 1)


class TestAUC:
    def test_perfect_separation(self):
        labels = np.array([0, 0, 0, 1, 1, 1], dtype=float)
        scores = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
        assert _compute_auc(labels, scores) == pytest.approx(1.0)

    def test_random(self):
        labels = np.array([0, 1, 0, 1], dtype=float)
        scores = np.array([0.5, 0.5, 0.5, 0.5])
        assert _compute_auc(labels, scores) == pytest.approx(0.5)

    def test_reversed(self):
        labels = np.array([1, 1, 0, 0], dtype=float)
        scores = np.array([0.1, 0.2, 0.8, 0.9])
        assert _compute_auc(labels, scores) == pytest.approx(0.0)

    def test_no_positive(self):
        labels = np.array([0, 0, 0], dtype=float)
        scores = np.array([0.1, 0.5, 0.9])
        assert _compute_auc(labels, scores) == 0.5

    def test_realistic(self):
        rng = np.random.RandomState(42)
        n = 100
        labels = np.zeros(n)
        labels[:20] = 1
        rng.shuffle(labels)
        # Scores correlated with labels
        scores = labels * 0.5 + rng.randn(n) * 0.3
        auc = _compute_auc(labels, scores)
        assert 0.5 < auc < 1.0  # better than random


class TestTrainWalkForward:
    def test_basic_training(self):
        """Should produce a trained model with fold results."""
        ds = _make_dataset(n=300, n_pos=30, start_year=2010)
        model = train_walk_forward(
            ds,
            fold_years=[2016, 2017, 2018],
            num_boost_round=20,
            early_stopping_rounds=5,
        )
        assert isinstance(model, TrainedModel)
        assert len(model.fold_results) > 0
        assert model.feature_names == list(ALL_FEATURES)
        assert len(model.feature_importance) > 0

    def test_fold_metrics(self):
        """Each fold should have reasonable metrics."""
        ds = _make_dataset(n=400, n_pos=40, start_year=2010)
        model = train_walk_forward(
            ds,
            fold_years=[2015, 2016, 2017],
            num_boost_round=20,
            early_stopping_rounds=5,
        )
        for fr in model.fold_results:
            assert fr.n_train > 0
            assert fr.n_test > 0
            assert 0 <= fr.auc <= 1

    def test_aggregate_metrics(self):
        ds = _make_dataset(n=300, n_pos=30, start_year=2010)
        model = train_walk_forward(
            ds,
            fold_years=[2016, 2017, 2018],
            num_boost_round=20,
            early_stopping_rounds=5,
        )
        agg = model.aggregate_metrics
        assert "mean_auc" in agg
        assert "n_folds" in agg
        assert agg["n_folds"] > 0

    def test_predict_proba(self):
        """predict_proba should return calibrated probabilities."""
        ds = _make_dataset(n=300, n_pos=30, start_year=2010)
        model = train_walk_forward(
            ds,
            fold_years=[2016, 2017, 2018],
            num_boost_round=20,
            early_stopping_rounds=5,
        )
        probs = model.predict_proba(ds.X[:10])
        assert len(probs) == 10
        assert np.all(probs >= 0)
        assert np.all(probs <= 1)

    def test_serialization_roundtrip(self):
        """Model should survive serialize/deserialize."""
        ds = _make_dataset(n=200, n_pos=20, start_year=2010)
        model = train_walk_forward(
            ds,
            fold_years=[2016, 2017],
            num_boost_round=10,
            early_stopping_rounds=5,
        )

        blob = model.serialize()
        assert isinstance(blob, bytes)

        restored = TrainedModel.deserialize(
            blob,
            fold_results=model.fold_results,
            feature_importance=model.feature_importance,
            train_config=model.train_config,
        )

        # Predictions should match
        orig_preds = model.predict_proba(ds.X[:5])
        rest_preds = restored.predict_proba(ds.X[:5])
        np.testing.assert_allclose(orig_preds, rest_preds, atol=1e-6)

    def test_skips_small_folds(self):
        """Folds with too few samples should be skipped."""
        ds = _make_dataset(n=100, n_pos=10, start_year=2018)
        # Only 2 years of data, folds before 2018 will have 0 training data
        model = train_walk_forward(
            ds,
            fold_years=[2015, 2016],
            num_boost_round=10,
            early_stopping_rounds=5,
        )
        assert len(model.fold_results) == 0

    def test_logging(self):
        """Log function should be called."""
        ds = _make_dataset(n=200, n_pos=20, start_year=2010)
        logs = []
        model = train_walk_forward(
            ds,
            fold_years=[2016],
            num_boost_round=10,
            early_stopping_rounds=5,
            log_fn=logs.append,
        )
        assert len(logs) > 0
        assert any("Fold 2016" in l for l in logs)

    def test_with_missing_values(self):
        """Should handle NaN features (LightGBM native support)."""
        ds = _make_dataset(n=300, n_pos=30, start_year=2010)
        # Inject NaNs into last 5 features
        rng = np.random.RandomState(99)
        mask = rng.rand(300, 5) < 0.3
        ds.X[:, -5:][mask] = np.nan

        model = train_walk_forward(
            ds,
            fold_years=[2016, 2017],
            num_boost_round=10,
            early_stopping_rounds=5,
        )
        assert len(model.fold_results) > 0

    def test_feature_importance_sums_to_one(self):
        """Feature importance should sum to approximately 1."""
        ds = _make_dataset(n=300, n_pos=30, start_year=2010)
        model = train_walk_forward(
            ds,
            fold_years=[2016, 2017],
            num_boost_round=20,
            early_stopping_rounds=5,
        )
        if model.feature_importance:
            total = sum(model.feature_importance.values())
            assert total == pytest.approx(1.0, abs=0.01)
