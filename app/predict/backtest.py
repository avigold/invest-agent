"""ML/PARQUET SCORING SYSTEM — backtesting framework.

Part of the ML/Parquet scoring system. Do not confuse with the deterministic
system (scorer.py, strategy.py, features.py).

Evaluates model predictions against historical outcomes using the validated
methodology: top-50 equal-weight portfolio per fold, with company name
deduplication (matching scripts/gen_excel_deduped.py exactly).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.predict.model import TrainedModel, _apply_platt
from app.predict.dataset import Dataset

# Portfolio size — matches validated backtest (scripts/gen_excel_deduped.py)
_BACKTEST_TOP_N = 50


@dataclass
class FoldBacktest:
    """Backtest results for a single fold year."""

    year: int
    n_positions: int
    positions: list[dict]          # [{ticker, weight, probability, actual_return, hit}]
    portfolio_return: float        # Weighted portfolio return
    hit_rate: float                # Fraction of positions that were winners
    total_invested: float          # Sum of weights (may be < 1 if fewer than TOP_N stocks)


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

    Replicates the validated methodology (scripts/gen_excel_deduped.py):
    1. Calibrate raw predictions via Platt scaling (ranking preserved)
    2. Sort by probability descending
    3. Deduplicate by company name when available (ParquetDataset)
    4. Select top 50
    5. Equal weight: 2% each (1/50)
    6. No return cap, no minimum probability, no constraints

    Hit = outperformer (label == 1), NOT a return threshold.

    Args:
        model: Trained model with fold results.
        dataset: Dataset with metadata. If a ParquetDataset, company name
            deduplication is applied per fold.

    Returns:
        BacktestResults with per-fold and aggregate metrics.
    """
    fold_backtests: list[FoldBacktest] = []
    all_predicted: list[float] = []
    all_actual: list[int] = []

    # Check if dataset has company_names (ParquetDataset)
    has_company_names = (
        hasattr(dataset, "company_names")
        and len(getattr(dataset, "company_names", [])) > 0
    )
    # Check if dataset has forward_returns array (ParquetDataset)
    has_forward_returns = (
        hasattr(dataset, "forward_returns")
        and getattr(dataset, "forward_returns", None) is not None
        and len(getattr(dataset, "forward_returns", [])) > 0
    )

    for fold in model.fold_results:
        # Calibrate predictions (Platt scaling is monotonic — ranking preserved)
        probs = _apply_platt(fold.predictions, model.platt_a, model.platt_b)

        # Build per-stock data for this fold
        stocks: list[dict] = []
        for idx_in_fold, global_idx in enumerate(fold.test_indices):
            if has_forward_returns:
                # ParquetDataset path
                if global_idx >= len(dataset.tickers):
                    continue
                ticker = dataset.tickers[global_idx]
                company_name = dataset.company_names[global_idx] if has_company_names else ""
                forward_return = float(dataset.forward_returns[global_idx])
                label = int(dataset.y[global_idx])
            else:
                # Dataset path (deterministic system)
                if global_idx >= len(dataset.meta):
                    continue
                meta = dataset.meta[global_idx]
                ticker = meta.ticker
                company_name = ""
                forward_return = meta.forward_return
                label = 1 if meta.label == "winner" else 0

            stocks.append({
                "ticker": ticker,
                "company_name": company_name,
                "probability": float(probs[idx_in_fold]),
                "forward_return": forward_return,
                "label": label,
            })

        # Collect for calibration (before dedup/selection)
        for s in stocks:
            all_predicted.append(s["probability"])
            all_actual.append(s["label"])

        # Sort by probability descending
        stocks.sort(key=lambda s: -s["probability"])

        # Deduplicate by company name (matches gen_excel_deduped.py)
        if has_company_names:
            seen: set[str] = set()
            deduped: list[dict] = []
            for s in stocks:
                key = s["company_name"].strip().lower()
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                deduped.append(s)
            stocks = deduped

        # Select top N — no minimum probability, no constraints
        top_n = stocks[:_BACKTEST_TOP_N]
        weight = round(1.0 / _BACKTEST_TOP_N, 4) if _BACKTEST_TOP_N > 0 else 0.0

        # Evaluate
        positions_data: list[dict] = []
        total_hits = 0
        portfolio_return = 0.0

        for s in top_n:
            actual = s["forward_return"]
            is_hit = s["label"] == 1  # Hit = outperformer (label == winner)
            if is_hit:
                total_hits += 1

            # No return cap — matches validated methodology
            portfolio_return += weight * actual

            positions_data.append({
                "ticker": s["ticker"],
                "weight": weight,
                "probability": round(s["probability"], 4),
                "actual_return": round(actual, 4),
                "hit": is_hit,
            })

        n_pos = len(top_n)
        total_invested = round(weight * n_pos, 4)

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

    # Sharpe (annualised, assuming annual returns)
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
