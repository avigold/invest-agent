"""LightGBM model training with walk-forward cross-validation and Platt scaling.

Trains a binary classifier to predict whether an observation will be a
"winner" (4x+ forward return). Uses walk-forward CV to prevent look-ahead
bias, and Platt scaling to produce calibrated probabilities.
"""
from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from typing import Callable

import lightgbm as lgb
import numpy as np

from app.predict.dataset import Dataset

MODEL_VERSION = "predictor_v1"

# Conservative hyperparameters for small datasets (~2000 obs)
DEFAULT_PARAMS: dict = {
    "objective": "binary",
    "metric": "auc",
    "num_leaves": 15,
    "min_data_in_leaf": 10,
    "learning_rate": 0.05,
    "feature_fraction": 0.7,
    "bagging_fraction": 0.7,
    "bagging_freq": 5,
    "verbose": -1,
}

DEFAULT_NUM_BOOST_ROUND = 300
DEFAULT_EARLY_STOPPING_ROUNDS = 30

# Walk-forward fold years (train on < year, test on == year)
DEFAULT_FOLD_YEARS = list(range(2015, 2021))  # 2015..2020


@dataclass
class FoldResult:
    """Metrics for a single walk-forward fold."""

    year: int
    n_train: int
    n_test: int
    n_train_pos: int
    n_test_pos: int
    auc: float
    predictions: np.ndarray    # raw scores for test set
    labels: np.ndarray         # true labels for test set
    test_indices: np.ndarray   # indices into the full dataset


@dataclass
class TrainedModel:
    """Output of model training."""

    booster: lgb.Booster
    platt_a: float
    platt_b: float
    feature_names: list[str]
    fold_results: list[FoldResult]
    feature_importance: dict[str, float]
    train_config: dict = field(default_factory=dict)

    @property
    def aggregate_metrics(self) -> dict:
        """Compute aggregate metrics across all folds."""
        if not self.fold_results:
            return {}
        aucs = [f.auc for f in self.fold_results]
        return {
            "mean_auc": float(np.mean(aucs)),
            "std_auc": float(np.std(aucs)),
            "min_auc": float(np.min(aucs)),
            "max_auc": float(np.max(aucs)),
            "n_folds": len(self.fold_results),
            "total_test_obs": sum(f.n_test for f in self.fold_results),
            "total_test_pos": sum(f.n_test_pos for f in self.fold_results),
        }

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict calibrated probabilities for new data.

        Args:
            X: Feature matrix (n_samples, n_features).

        Returns:
            Array of calibrated probabilities.
        """
        raw = self.booster.predict(X)
        return _apply_platt(raw, self.platt_a, self.platt_b)

    def serialize(self) -> bytes:
        """Serialize model to bytes for storage."""
        return pickle.dumps({
            "booster_str": self.booster.model_to_string(),
            "platt_a": self.platt_a,
            "platt_b": self.platt_b,
            "feature_names": self.feature_names,
        })

    @classmethod
    def deserialize(cls, data: bytes, fold_results: list | None = None,
                    feature_importance: dict | None = None,
                    train_config: dict | None = None) -> "TrainedModel":
        """Deserialize model from bytes."""
        d = pickle.loads(data)  # noqa: S301
        booster = lgb.Booster(model_str=d["booster_str"])
        return cls(
            booster=booster,
            platt_a=d["platt_a"],
            platt_b=d["platt_b"],
            feature_names=d["feature_names"],
            fold_results=fold_results or [],
            feature_importance=feature_importance or {},
            train_config=train_config or {},
        )


# ---------------------------------------------------------------------------
# Platt Scaling (calibration without sklearn)
# ---------------------------------------------------------------------------


def platt_scale(
    raw_scores: np.ndarray,
    labels: np.ndarray,
    max_iter: int = 100,
    tol: float = 1e-7,
) -> tuple[float, float]:
    """Fit Platt scaling parameters A, B.

    Fits P(y=1|f) = 1 / (1 + exp(A*f + B)) via Newton's method.
    Uses the improved target values from Platt (1999).

    Args:
        raw_scores: Model raw output scores.
        labels: Binary labels (0 or 1).

    Returns:
        (A, B) parameters for the sigmoid.
    """
    n = len(labels)
    n_pos = labels.sum()
    n_neg = n - n_pos

    # Target values (Bayesian prior correction)
    t_pos = (n_pos + 1) / (n_pos + 2)
    t_neg = 1 / (n_neg + 2)
    targets = np.where(labels > 0.5, t_pos, t_neg)

    A = 0.0
    B = math.log((n_neg + 1) / (n_pos + 1))

    for _ in range(max_iter):
        # Compute sigmoid
        fApB = raw_scores * A + B
        # Numerically stable sigmoid
        p = np.where(
            fApB >= 0,
            np.exp(-fApB) / (1 + np.exp(-fApB)),
            1.0 / (1 + np.exp(fApB)),
        )
        p = np.clip(p, 1e-15, 1 - 1e-15)

        # Gradient and Hessian
        d1 = targets - p
        d2 = p * (1 - p)

        # Newton update
        g_a = float((d1 * raw_scores).sum())
        g_b = float(d1.sum())
        h_aa = float((d2 * raw_scores * raw_scores).sum())
        h_bb = float(d2.sum())
        h_ab = float((d2 * raw_scores).sum())

        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-15:
            break

        dA = -(h_bb * g_a - h_ab * g_b) / det
        dB = -(h_aa * g_b - h_ab * g_a) / det

        A += dA
        B += dB

        if abs(dA) < tol and abs(dB) < tol:
            break

    return A, B


def _apply_platt(raw_scores: np.ndarray, A: float, B: float) -> np.ndarray:
    """Apply Platt scaling to get calibrated probabilities."""
    fApB = raw_scores * A + B
    return np.where(
        fApB >= 0,
        np.exp(-fApB) / (1 + np.exp(-fApB)),
        1.0 / (1 + np.exp(fApB)),
    )


# ---------------------------------------------------------------------------
# AUC computation (no sklearn)
# ---------------------------------------------------------------------------


def _compute_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """Compute ROC AUC using the Mann-Whitney U statistic.

    Args:
        labels: Binary labels (0 or 1).
        scores: Predicted scores (higher = more likely positive).

    Returns:
        AUC score between 0 and 1.
    """
    pos = scores[labels > 0.5]
    neg = scores[labels < 0.5]

    if len(pos) == 0 or len(neg) == 0:
        return 0.5

    # Sort and count via rank-based method
    n_pos = len(pos)
    n_neg = len(neg)

    # Combined array with label tracking
    combined = np.concatenate([pos, neg])
    labels_combined = np.concatenate([np.ones(n_pos), np.zeros(n_neg)])

    order = combined.argsort()
    labels_sorted = labels_combined[order]
    ranks = np.arange(1, len(combined) + 1, dtype=np.float64)

    # Handle ties: assign average rank
    sorted_scores = combined[order]
    i = 0
    while i < len(sorted_scores):
        j = i
        while j < len(sorted_scores) and sorted_scores[j] == sorted_scores[i]:
            j += 1
        avg_rank = (ranks[i] + ranks[j - 1]) / 2
        ranks[i:j] = avg_rank
        i = j

    pos_rank_sum = ranks[labels_sorted > 0.5].sum()
    auc = (pos_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(np.clip(auc, 0, 1))


# ---------------------------------------------------------------------------
# Walk-Forward Training
# ---------------------------------------------------------------------------


def train_walk_forward(
    dataset: Dataset,
    fold_years: list[int] | None = None,
    params: dict | None = None,
    num_boost_round: int = DEFAULT_NUM_BOOST_ROUND,
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS,
    log_fn: Callable[[str], None] | None = None,
) -> TrainedModel:
    """Train LightGBM with walk-forward cross-validation.

    For each fold year, trains on all observations before that year and
    tests on observations from that year. Collects out-of-sample predictions
    across all folds for Platt scaling calibration.

    Args:
        dataset: Dataset with feature matrix and labels.
        fold_years: Years to use as test folds (default: 2015-2020).
        params: LightGBM parameters (default: conservative preset).
        num_boost_round: Max boosting rounds.
        early_stopping_rounds: Early stopping patience.
        log_fn: Optional logging callback.

    Returns:
        TrainedModel with the final booster and calibrated probabilities.
    """
    log = log_fn or (lambda _: None)
    fold_years = fold_years or DEFAULT_FOLD_YEARS
    params = {**DEFAULT_PARAMS, **(params or {})}

    # Extract observation years from metadata
    obs_years = np.array([m.obs_date.year for m in dataset.meta])

    fold_results: list[FoldResult] = []
    all_oof_scores: list[np.ndarray] = []
    all_oof_labels: list[np.ndarray] = []

    for year in fold_years:
        train_mask = obs_years < year
        test_mask = obs_years == year

        n_train = int(train_mask.sum())
        n_test = int(test_mask.sum())

        if n_train < 20 or n_test < 5:
            log(f"  Fold {year}: skipped (train={n_train}, test={n_test})")
            continue

        X_train = dataset.X[train_mask]
        y_train = dataset.y[train_mask]
        X_test = dataset.X[test_mask]
        y_test = dataset.y[test_mask]

        # Compute scale_pos_weight
        n_pos_train = int(y_train.sum())
        n_neg_train = n_train - n_pos_train
        if n_pos_train > 0:
            params["scale_pos_weight"] = n_neg_train / n_pos_train

        train_ds = lgb.Dataset(X_train, label=y_train,
                               feature_name=dataset.feature_names,
                               free_raw_data=False)
        valid_ds = lgb.Dataset(X_test, label=y_test,
                               feature_name=dataset.feature_names,
                               free_raw_data=False)

        callbacks = [lgb.early_stopping(early_stopping_rounds, verbose=False)]
        booster = lgb.train(
            params,
            train_ds,
            num_boost_round=num_boost_round,
            valid_sets=[valid_ds],
            callbacks=callbacks,
        )

        preds = booster.predict(X_test)
        auc = _compute_auc(y_test, preds)

        test_indices = np.where(test_mask)[0]
        fr = FoldResult(
            year=year,
            n_train=n_train,
            n_test=n_test,
            n_train_pos=n_pos_train,
            n_test_pos=int(y_test.sum()),
            auc=auc,
            predictions=preds,
            labels=y_test,
            test_indices=test_indices,
        )
        fold_results.append(fr)
        all_oof_scores.append(preds)
        all_oof_labels.append(y_test)

        log(f"  Fold {year}: AUC={auc:.3f} (train={n_train}, test={n_test}, "
            f"pos={n_pos_train}/{int(y_test.sum())})")

    # Final model: train on all data
    log("Training final model on all data...")
    n_pos_all = int(dataset.y.sum())
    n_neg_all = len(dataset.y) - n_pos_all
    if n_pos_all > 0:
        params["scale_pos_weight"] = n_neg_all / n_pos_all

    final_train = lgb.Dataset(dataset.X, label=dataset.y,
                              feature_name=dataset.feature_names,
                              free_raw_data=False)
    final_booster = lgb.train(
        params,
        final_train,
        num_boost_round=num_boost_round,
    )

    # Platt scaling on pooled out-of-fold predictions
    if all_oof_scores:
        oof_scores = np.concatenate(all_oof_scores)
        oof_labels = np.concatenate(all_oof_labels)
        platt_a, platt_b = platt_scale(oof_scores, oof_labels)
        log(f"Platt calibration: A={platt_a:.4f}, B={platt_b:.4f}")
    else:
        platt_a, platt_b = -1.0, 0.0
        log("WARNING: No fold results — using default Platt params")

    # Feature importance (gain-based)
    importance = final_booster.feature_importance(importance_type="gain")
    total = importance.sum()
    feat_imp = {}
    if total > 0:
        for name, imp in zip(dataset.feature_names, importance):
            feat_imp[name] = float(imp / total)

    # Sort by importance descending
    feat_imp = dict(sorted(feat_imp.items(), key=lambda x: -x[1]))

    log(f"Top features: {', '.join(f'{k}={v:.3f}' for k, v in list(feat_imp.items())[:5])}")

    return TrainedModel(
        booster=final_booster,
        platt_a=platt_a,
        platt_b=platt_b,
        feature_names=dataset.feature_names,
        fold_results=fold_results,
        feature_importance=feat_imp,
        train_config={
            "params": params,
            "num_boost_round": num_boost_round,
            "early_stopping_rounds": early_stopping_rounds,
            "fold_years": fold_years,
            "n_observations": dataset.n_observations,
            "n_winners": dataset.n_winners,
            "base_rate": dataset.base_rate,
            "model_version": MODEL_VERSION,
        },
    )
