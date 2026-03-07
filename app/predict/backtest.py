"""Backtesting framework — evaluate model predictions against historical outcomes.

Uses walk-forward fold results to simulate portfolio construction and
measure actual performance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.predict.model import FoldResult, TrainedModel, _apply_platt
from app.predict.dataset import Dataset
from app.predict.strategy import Position, build_portfolio


@dataclass
class FoldBacktest:
    """Backtest results for a single fold year."""

    year: int
    n_positions: int
    positions: list[dict]          # [{ticker, weight, probability, actual_return, hit}]
    portfolio_return: float        # Weighted portfolio return
    hit_rate: float                # Fraction of positions that were winners
    total_invested: float          # Sum of weights (may be < 1 if few positions)


@dataclass
class BacktestResults:
    """Aggregate backtest results across all folds."""

    folds: list[FoldBacktest]
    total_return: float            # Compound return across all folds
    cagr: float                    # Compound annual growth rate
    sharpe: float                  # Sharpe ratio of fold returns
    max_drawdown: float            # Worst single-fold loss
    hit_rate: float                # Overall hit rate across all positions
    n_total_positions: int
    n_total_hits: int
    calibration: list[dict]        # [{bucket, predicted_avg, actual_avg, count}]


def run_backtest(
    model: TrainedModel,
    dataset: Dataset,
) -> BacktestResults:
    """Run backtest using walk-forward fold results.

    For each fold, calibrates the raw predictions using Platt scaling,
    builds a portfolio, and evaluates against actual forward returns.

    Args:
        model: Trained model with fold results.
        dataset: Dataset with metadata (forward returns).

    Returns:
        BacktestResults with per-fold and aggregate metrics.
    """
    fold_backtests: list[FoldBacktest] = []
    all_predicted: list[float] = []
    all_actual: list[int] = []

    for fold in model.fold_results:
        # Calibrate predictions
        probs = _apply_platt(fold.predictions, model.platt_a, model.platt_b)

        # Build prediction dicts for portfolio construction
        pred_dicts = []
        for idx_in_fold, global_idx in enumerate(fold.test_indices):
            if global_idx >= len(dataset.meta):
                continue
            meta = dataset.meta[global_idx]
            pred_dicts.append({
                "ticker": meta.ticker,
                "probability": float(probs[idx_in_fold]),
                "sector": "Unknown",  # Sector not stored in meta
                "forward_return": meta.forward_return,
                "label": meta.label,
            })

        # Collect for calibration
        for pd_item in pred_dicts:
            all_predicted.append(pd_item["probability"])
            all_actual.append(1 if pd_item["label"] == "winner" else 0)

        # Build portfolio
        portfolio = build_portfolio(pred_dicts)

        # Evaluate
        positions_data = []
        total_hits = 0
        portfolio_return = 0.0
        total_invested = sum(p.weight for p in portfolio)

        for pos in portfolio:
            # Find the actual forward return for this position
            actual = next(
                (d["forward_return"] for d in pred_dicts if d["ticker"] == pos.ticker),
                0.0,
            )
            is_hit = actual >= 3.0  # 4x = 300% return threshold
            if is_hit:
                total_hits += 1

            # Cap individual position return (can't lose more than position)
            pos_return = max(actual, -1.0)
            portfolio_return += pos.weight * pos_return

            positions_data.append({
                "ticker": pos.ticker,
                "weight": round(pos.weight, 4),
                "probability": round(pos.probability, 4),
                "actual_return": round(actual, 4),
                "hit": is_hit,
            })

        # Cash portion earns 0
        # portfolio_return already accounts for invested portion

        n_pos = len(portfolio)
        fold_backtests.append(FoldBacktest(
            year=fold.year,
            n_positions=n_pos,
            positions=positions_data,
            portfolio_return=portfolio_return,
            hit_rate=total_hits / n_pos if n_pos > 0 else 0.0,
            total_invested=total_invested,
        ))

    # Aggregate metrics
    returns = [f.portfolio_return for f in fold_backtests]
    n_total = sum(f.n_positions for f in fold_backtests)
    n_hits = sum(
        sum(1 for p in f.positions if p["hit"]) for f in fold_backtests
    )

    # Compound return
    compound = 1.0
    for r in returns:
        compound *= (1 + r)
    total_return = compound - 1

    # CAGR
    n_years = len(returns) if returns else 1
    if compound > 0:
        cagr = compound ** (1 / n_years) - 1
    else:
        cagr = -1.0

    # Sharpe (annualized, assuming annual returns)
    if len(returns) >= 2:
        mean_r = np.mean(returns)
        std_r = np.std(returns, ddof=1)
        sharpe = float(mean_r / std_r) if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    # Max drawdown (worst single fold)
    max_dd = min(returns) if returns else 0.0

    # Calibration by decile
    calibration = _compute_calibration(all_predicted, all_actual)

    return BacktestResults(
        folds=fold_backtests,
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=max_dd,
        hit_rate=n_hits / n_total if n_total > 0 else 0.0,
        n_total_positions=n_total,
        n_total_hits=n_hits,
        calibration=calibration,
    )


def _compute_calibration(
    predicted: list[float],
    actual: list[int],
    n_buckets: int = 5,
) -> list[dict]:
    """Compute calibration buckets.

    Groups predictions into equal-width buckets and compares
    predicted average probability vs actual hit rate.
    """
    if not predicted:
        return []

    pred = np.array(predicted)
    act = np.array(actual)

    edges = np.linspace(0, 1, n_buckets + 1)
    buckets = []

    for i in range(n_buckets):
        lo, hi = edges[i], edges[i + 1]
        if i == n_buckets - 1:
            mask = (pred >= lo) & (pred <= hi)
        else:
            mask = (pred >= lo) & (pred < hi)

        count = int(mask.sum())
        if count == 0:
            continue

        buckets.append({
            "bucket": f"{lo:.0%}-{hi:.0%}",
            "predicted_avg": float(pred[mask].mean()),
            "actual_avg": float(act[mask].mean()),
            "count": count,
        })

    return buckets


def backtest_to_dict(results: BacktestResults) -> dict:
    """Serialize BacktestResults to a JSON-compatible dict for storage."""
    return {
        "folds": [
            {
                "year": f.year,
                "n_positions": f.n_positions,
                "positions": f.positions,
                "portfolio_return": round(f.portfolio_return, 4),
                "hit_rate": round(f.hit_rate, 4),
                "total_invested": round(f.total_invested, 4),
            }
            for f in results.folds
        ],
        "total_return": round(results.total_return, 4),
        "cagr": round(results.cagr, 4),
        "sharpe": round(results.sharpe, 4),
        "max_drawdown": round(results.max_drawdown, 4),
        "hit_rate": round(results.hit_rate, 4),
        "n_total_positions": results.n_total_positions,
        "n_total_hits": results.n_total_hits,
        "calibration": results.calibration,
    }
