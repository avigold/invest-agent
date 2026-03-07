"""Tests for app.predict.strategy + app.predict.backtest."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.predict.backtest import (
    BacktestResults,
    FoldBacktest,
    _compute_calibration,
    backtest_to_dict,
    run_backtest,
)
from app.predict.dataset import Dataset, ObservationMeta
from app.predict.features import ALL_FEATURES
from app.predict.model import FoldResult, TrainedModel, train_walk_forward
from app.predict.strategy import (
    Position,
    build_portfolio,
    kelly_fraction,
)


# ---------------------------------------------------------------------------
# Strategy tests
# ---------------------------------------------------------------------------


class TestKellyFraction:
    def test_zero_probability(self):
        assert kelly_fraction(0.0) == 0.0

    def test_low_probability(self):
        # Very low probability → no edge
        result = kelly_fraction(0.01)
        assert result == 0.0  # negative Kelly → clamped to 0

    def test_moderate_probability(self):
        result = kelly_fraction(0.20)
        assert result > 0
        assert result < 0.10  # quarter-Kelly with moderate prob

    def test_high_probability(self):
        result = kelly_fraction(0.50)
        assert result > kelly_fraction(0.20)

    def test_full_kelly_vs_quarter(self):
        full = kelly_fraction(0.30, fraction=1.0)
        quarter = kelly_fraction(0.30, fraction=0.25)
        assert quarter == pytest.approx(full * 0.25, rel=0.01)

    def test_custom_win_loss(self):
        result = kelly_fraction(0.30, avg_win=5.0, avg_loss=-0.30)
        assert result > 0

    def test_negative_avg_win(self):
        assert kelly_fraction(0.30, avg_win=0) == 0.0


class TestBuildPortfolio:
    def test_basic_portfolio(self):
        preds = [
            {"ticker": "AAPL", "probability": 0.25, "sector": "Tech"},
            {"ticker": "GOOG", "probability": 0.15, "sector": "Tech"},
            {"ticker": "JPM", "probability": 0.10, "sector": "Finance"},
        ]
        positions = build_portfolio(preds)
        assert len(positions) > 0
        assert all(p.weight > 0 for p in positions)
        assert all(p.weight <= 0.10 for p in positions)

    def test_filters_low_probability(self):
        preds = [
            {"ticker": "AAPL", "probability": 0.25, "sector": "Tech"},
            {"ticker": "JUNK", "probability": 0.02, "sector": "Other"},  # below threshold
        ]
        positions = build_portfolio(preds)
        tickers = [p.ticker for p in positions]
        assert "JUNK" not in tickers

    def test_sector_constraint(self):
        # 5 stocks all in same sector → sector cap of 30% kicks in
        preds = [
            {"ticker": f"T{i}", "probability": 0.30, "sector": "Tech"}
            for i in range(5)
        ]
        positions = build_portfolio(preds, max_sector=0.30)
        total_weight = sum(p.weight for p in positions)
        assert total_weight <= 0.31  # approximate

    def test_max_position_constraint(self):
        preds = [
            {"ticker": "AAPL", "probability": 0.80, "sector": "Tech"},
        ]
        positions = build_portfolio(preds, max_position=0.10)
        assert positions[0].weight <= 0.10

    def test_empty_predictions(self):
        assert build_portfolio([]) == []

    def test_sorts_by_weight(self):
        preds = [
            {"ticker": "A", "probability": 0.10, "sector": "S1"},
            {"ticker": "B", "probability": 0.30, "sector": "S2"},
            {"ticker": "C", "probability": 0.20, "sector": "S3"},
        ]
        positions = build_portfolio(preds)
        for i in range(len(positions) - 1):
            assert positions[i].weight >= positions[i + 1].weight

    def test_normalization(self):
        """If total weights exceed 1, they should be normalized."""
        preds = [
            {"ticker": f"T{i}", "probability": 0.40, "sector": f"S{i}"}
            for i in range(20)
        ]
        positions = build_portfolio(preds)
        total = sum(p.weight for p in positions)
        assert total <= 1.01


class TestPositionDataclass:
    def test_expected_return(self):
        pos = Position(
            ticker="AAPL",
            probability=0.20,
            kelly_raw=0.05,
            weight=0.05,
            sector="Tech",
            expected_return=0.20 * 3.0 + 0.80 * (-0.50),
        )
        assert pos.expected_return == pytest.approx(0.20, abs=0.01)


# ---------------------------------------------------------------------------
# Backtest tests
# ---------------------------------------------------------------------------


def _make_synthetic_model_and_dataset():
    """Create a simple model and dataset for backtest testing."""
    rng = np.random.RandomState(42)
    n = 300
    n_features = len(ALL_FEATURES)
    X = rng.randn(n, n_features)
    y = np.zeros(n)
    y[:30] = 1.0  # 10% winners
    rng.shuffle(y)

    # Add signal
    for i in range(n):
        if y[i] == 1:
            X[i, :3] += 1.5

    years = np.array([2010 + i // 30 for i in range(n)])
    meta = [
        ObservationMeta(
            ticker=f"T{i}",
            obs_date=date(int(years[i]), 6, 30),
            forward_return=4.0 if y[i] == 1 else 0.2,
            label="winner" if y[i] == 1 else "normal",
        )
        for i in range(n)
    ]

    ds = Dataset(X=X, y=y, feature_names=list(ALL_FEATURES), meta=meta)
    model = train_walk_forward(
        ds,
        fold_years=[2015, 2016, 2017],
        num_boost_round=20,
        early_stopping_rounds=5,
    )
    return model, ds


class TestRunBacktest:
    def test_basic_backtest(self):
        model, ds = _make_synthetic_model_and_dataset()
        results = run_backtest(model, ds)
        assert isinstance(results, BacktestResults)
        assert len(results.folds) > 0

    def test_fold_metrics(self):
        model, ds = _make_synthetic_model_and_dataset()
        results = run_backtest(model, ds)
        for fold in results.folds:
            assert isinstance(fold, FoldBacktest)
            assert fold.year > 0
            assert fold.n_positions >= 0
            assert 0 <= fold.hit_rate <= 1.0

    def test_aggregate_metrics(self):
        model, ds = _make_synthetic_model_and_dataset()
        results = run_backtest(model, ds)
        assert isinstance(results.sharpe, float)
        assert isinstance(results.total_return, float)
        assert isinstance(results.cagr, float)
        assert isinstance(results.max_drawdown, float)
        assert results.n_total_positions >= 0

    def test_serialization(self):
        model, ds = _make_synthetic_model_and_dataset()
        results = run_backtest(model, ds)
        d = backtest_to_dict(results)
        assert "folds" in d
        assert "total_return" in d
        assert "sharpe" in d
        assert "calibration" in d
        # All values should be JSON-serializable
        import json
        json.dumps(d)  # Should not raise


class TestCalibration:
    def test_basic_calibration(self):
        predicted = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        actual = [0, 0, 0, 0, 1, 1, 1, 1, 1]
        buckets = _compute_calibration(predicted, actual)
        assert len(buckets) > 0
        for b in buckets:
            assert "bucket" in b
            assert "predicted_avg" in b
            assert "actual_avg" in b
            assert "count" in b

    def test_empty(self):
        assert _compute_calibration([], []) == []

    def test_all_same_prediction(self):
        predicted = [0.5] * 10
        actual = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
        buckets = _compute_calibration(predicted, actual)
        assert len(buckets) >= 1
