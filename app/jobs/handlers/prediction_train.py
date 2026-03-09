"""Handler for prediction_train job command.

Trains a LightGBM model from Parquet training data using walk-forward CV,
runs backtesting, scores the current universe, and stores everything.

Uses the ML/Parquet scoring system (186 features, ~771k rows).
Do NOT confuse with the deterministic system (scorer.py, strategy.py, features.py).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PredictionModel, PredictionScore
from app.predict.backtest import backtest_to_dict, run_backtest
from app.predict.model import (
    PARQUET_EARLY_STOPPING_ROUNDS,
    PARQUET_FOLD_YEARS,
    PARQUET_HOLDOUT_YEAR,
    PARQUET_MODEL_VERSION,
    PARQUET_NUM_BOOST_ROUND,
    PARQUET_PARAMS,
    train_walk_forward_parquet,
)
from app.predict.parquet_dataset import load_parquet_dataset
from app.predict.parquet_scorer import score_from_parquet

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob

# Golden model files — NEVER overwrite these
_PROTECTED_FILES = {"seed32_v1.pkl", "seed32_v1_backup.pkl"}

# Default parquet path
_DEFAULT_PARQUET_PATH = "data/exports/training_features.parquet"

# Golden countries (24, no India)
_GOLDEN_COUNTRIES = [
    "US", "GB", "CA", "AU", "DE", "FR", "JP", "CH", "SE", "NL",
    "KR", "BR", "ZA", "SG", "HK", "NO", "DK", "FI", "IL", "NZ",
    "TW", "IE", "BE", "AT",
]


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


def _safe_save_model(model_blob: bytes, version: str, model_id: str) -> str | None:
    """Save model blob to data/models/ with safe naming.

    Returns the saved file path, or None if save was skipped.
    Never overwrites protected golden model files.
    """
    models_dir = "data/models"
    os.makedirs(models_dir, exist_ok=True)

    short_id = model_id[:8]
    filename = f"{version}_{short_id}.pkl"

    # Never overwrite protected files
    if filename in _PROTECTED_FILES:
        filename = f"{version}_{short_id}_new.pkl"

    filepath = os.path.join(models_dir, filename)

    # If file already exists, append counter
    if os.path.exists(filepath):
        for i in range(2, 100):
            candidate = os.path.join(models_dir, f"{version}_{short_id}_{i}.pkl")
            if not os.path.exists(candidate):
                filepath = candidate
                break
        else:
            return None  # Could not find a free filename

    # Final safety check: never overwrite protected files
    basename = os.path.basename(filepath)
    if basename in _PROTECTED_FILES:
        return None

    with open(filepath, "wb") as f:
        f.write(model_blob)

    return filepath


async def prediction_train_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Train a prediction model end-to-end using the ML/Parquet system."""
    params = job.params

    # ── Parse parameters with golden defaults ───────────────────────────
    seed = int(params.get("seed", 32))
    countries_raw = params.get("countries", ",".join(_GOLDEN_COUNTRIES))
    if isinstance(countries_raw, list):
        country_list = [c.strip().upper() for c in countries_raw]
    else:
        country_list = [c.strip().upper() for c in str(countries_raw).split(",")]

    min_dollar_volume = float(params.get("min_dollar_volume", 500_000))
    max_return_clip = float(params.get("max_return_clip", 10.0))
    return_threshold = float(params.get("return_threshold", 0.20))
    relative_to_country = bool(params.get("relative_to_country", True))
    half_life = float(params.get("half_life", 7.0))
    min_fiscal_year = int(params.get("min_fiscal_year", 2000))
    num_leaves = int(params.get("num_leaves", 63))

    fold_years_raw = params.get("fold_years", None)
    if fold_years_raw:
        if isinstance(fold_years_raw, list):
            fold_years = [int(y) for y in fold_years_raw]
        else:
            fold_years = [int(y.strip()) for y in str(fold_years_raw).split(",")]
    else:
        fold_years = list(PARQUET_FOLD_YEARS)

    holdout_year = int(params.get("holdout_year", PARQUET_HOLDOUT_YEAR))
    parquet_path = _DEFAULT_PARQUET_PATH

    # ── Build LightGBM params (COPY, never mutate PARQUET_PARAMS) ───────
    lgb_params = {
        **PARQUET_PARAMS,
        "num_leaves": num_leaves,
        "seed": seed,
        "data_random_seed": seed,
        "feature_fraction_seed": seed,
        "bagging_seed": seed,
    }

    # ── Full config for audit trail ─────────────────────────────────────
    train_config = {
        "model_version": PARQUET_MODEL_VERSION,
        "seed": seed,
        "countries": country_list,
        "min_dollar_volume": min_dollar_volume,
        "max_return_clip": max_return_clip,
        "return_threshold": return_threshold,
        "relative_to_country": relative_to_country,
        "half_life": half_life,
        "min_fiscal_year": min_fiscal_year,
        "num_leaves": num_leaves,
        "fold_years": fold_years,
        "holdout_year": holdout_year,
        "parquet_path": parquet_path,
        "num_boost_round": PARQUET_NUM_BOOST_ROUND,
        "early_stopping_rounds": PARQUET_EARLY_STOPPING_ROUNDS,
        "lgb_params": lgb_params,
    }

    # ── Phase 1: Log config ─────────────────────────────────────────────
    _log(job, "=== ML/Parquet Model Training ===")
    _log(job, f"  Seed: {seed}")
    _log(job, f"  Countries: {','.join(country_list)} ({len(country_list)})")
    _log(job, f"  Min dollar volume: ${min_dollar_volume:,.0f}")
    _log(job, f"  Max return clip: {max_return_clip}")
    _log(job, f"  Return threshold: {return_threshold} (relative_to_country={relative_to_country})")
    _log(job, f"  Half-life: {half_life} years")
    _log(job, f"  Min fiscal year: {min_fiscal_year}")
    _log(job, f"  Num leaves: {num_leaves}")
    _log(job, f"  Fold years: {fold_years}")
    _log(job, f"  Holdout year: {holdout_year}")
    _log(job, f"  Boost rounds: {PARQUET_NUM_BOOST_ROUND}, early stopping: {PARQUET_EARLY_STOPPING_ROUNDS}")

    # ── Phase 2: Load parquet dataset ───────────────────────────────────
    _log(job, "\n--- Loading Parquet dataset ---")
    dataset = load_parquet_dataset(
        parquet_path=parquet_path,
        min_fiscal_year=min_fiscal_year,
        half_life=half_life,
        min_dollar_volume=min_dollar_volume,
        allowed_countries=country_list,
        max_return_clip=max_return_clip,
        return_threshold=return_threshold,
        relative_to_country=relative_to_country,
        log_fn=lambda msg: _log(job, msg),
    )
    _log(job, f"Dataset: {dataset.n_observations} observations, "
               f"{dataset.n_features} features, "
               f"{dataset.n_winners} winners ({dataset.base_rate:.1%} base rate)")

    if dataset.n_winners < 5:
        _log(job, "ERROR: Fewer than 5 winners — model cannot learn")
        job.status = "failed"
        return

    # Store dataset stats in config
    train_config["n_observations"] = dataset.n_observations
    train_config["n_features"] = dataset.n_features
    train_config["n_winners"] = dataset.n_winners
    train_config["base_rate"] = round(dataset.base_rate, 4)

    # ── Phase 3: Train with walk-forward CV ─────────────────────────────
    _log(job, "\n--- Training model (walk-forward CV) ---")
    model = train_walk_forward_parquet(
        dataset=dataset,
        fold_years=fold_years,
        holdout_year=holdout_year,
        params=lgb_params,
        num_boost_round=PARQUET_NUM_BOOST_ROUND,
        early_stopping_rounds=PARQUET_EARLY_STOPPING_ROUNDS,
        log_fn=lambda msg: _log(job, msg),
    )

    agg = model.aggregate_metrics
    _log(job, f"\nAggregate results:")
    _log(job, f"  Mean AUC: {agg.get('mean_auc', 0):.4f} "
               f"(+/-{agg.get('std_auc', 0):.4f})")
    _log(job, f"  Folds: {agg.get('n_folds', 0)}")
    _log(job, f"  Total test observations: {agg.get('total_test_obs', 0)}")
    _log(job, f"  Total test positives: {agg.get('total_test_pos', 0)}")

    # ── Phase 4: Backtest ───────────────────────────────────────────────
    _log(job, "\n--- Running backtest ---")
    bt_results = run_backtest(model, dataset)
    _log(job, f"Backtest results:")
    _log(job, f"  Total return: {bt_results.total_return:.1%}")
    _log(job, f"  CAGR: {bt_results.cagr:.1%}")
    _log(job, f"  Sharpe: {bt_results.sharpe:.2f}")
    _log(job, f"  Max drawdown: {bt_results.max_drawdown:.1%}")
    _log(job, f"  Hit rate: {bt_results.hit_rate:.1%} "
               f"({bt_results.n_total_hits}/{bt_results.n_total_positions})")

    for fold in bt_results.folds:
        _log(job, f"  Year {fold.year}: return={fold.portfolio_return:.1%}, "
                   f"positions={fold.n_positions}, hit_rate={fold.hit_rate:.0%}")

    # ── Phase 5: Score current universe ─────────────────────────────────
    _log(job, "\n--- Scoring current universe ---")
    scored = score_from_parquet(
        parquet_path=parquet_path,
        model=model,
        model_config=train_config,
        log_fn=lambda msg: _log(job, msg),
    )

    if scored:
        _log(job, f"\nTop predictions:")
        for i, s in enumerate(scored[:10], 1):
            _log(job, f"  {i}. {s.ticker} ({s.country}): "
                       f"p={s.probability:.1%} ({s.confidence}), "
                       f"weight={s.suggested_weight:.1%}")

    # ── Phase 6: Store model and scores ─────────────────────────────────
    _log(job, "\n--- Storing model and scores ---")

    model_id = uuid.uuid4()

    # Override train_config on the TrainedModel so it's stored in DB
    model.train_config = train_config

    fold_metrics_json = [
        {
            "year": fr.year,
            "n_train": fr.n_train,
            "n_test": fr.n_test,
            "n_train_pos": fr.n_train_pos,
            "n_test_pos": fr.n_test_pos,
            "auc": round(fr.auc, 4),
        }
        for fr in model.fold_results
    ]

    async with session_factory() as db:
        # Auto-activate if this is the user's first model
        existing_count = (await db.execute(
            select(func.count()).select_from(PredictionModel)
            .where(PredictionModel.user_id == job.user_id)
        )).scalar() or 0
        auto_activate = existing_count == 0

        pred_model = PredictionModel(
            id=model_id,
            user_id=job.user_id,
            job_id=job.id,
            model_version=PARQUET_MODEL_VERSION,
            config=train_config,
            fold_metrics=fold_metrics_json,
            aggregate_metrics=agg,
            feature_importance=model.feature_importance,
            backtest_results=backtest_to_dict(bt_results),
            model_blob=model.serialize(),
            platt_a=model.platt_a,
            platt_b=model.platt_b,
            is_active=auto_activate,
        )
        db.add(pred_model)
        await db.flush()
        if auto_activate:
            _log(job, "Auto-activated as first model for user")

        _log(job, f"Model saved: {pred_model.id}")

        # Store PredictionScore rows (new model only — no deletes of other models)
        now = datetime.now(tz=timezone.utc)
        for s in scored:
            contrib = {"country": s.country, "sector": s.sector, **s.contributing_features}
            db.add(PredictionScore(
                id=uuid.uuid4(),
                model_id=pred_model.id,
                user_id=job.user_id,
                ticker=s.ticker,
                company_name=s.company_name,
                country=s.country,
                sector=s.sector,
                probability=s.probability,
                confidence_tier=s.confidence,
                kelly_fraction=s.kelly,
                suggested_weight=s.suggested_weight,
                contributing_features=contrib,
                feature_values=s.feature_values,
                scored_at=now,
                job_id=job.id,
            ))

        await db.commit()
        _log(job, f"Scores saved: {len(scored)} companies")

    # ── Phase 7: Save model blob to disk (safe naming) ──────────────────
    model_blob = model.serialize()
    saved_path = _safe_save_model(model_blob, PARQUET_MODEL_VERSION, str(model_id))
    if saved_path:
        _log(job, f"Model blob backed up: {saved_path}")
    else:
        _log(job, "WARNING: Could not save model blob to disk")

    _log(job, "\n=== Training Complete ===")
    _log(job, f"Model ID: {model_id}")
    _log(job, f"AUC: {agg.get('mean_auc', 0):.4f}")
    _log(job, f"Backtest Sharpe: {bt_results.sharpe:.2f}")
    _log(job, f"Backtest CAGR: {bt_results.cagr:.1%}")
    if scored:
        _log(job, f"Top pick: {scored[0].ticker} (p={scored[0].probability:.1%})")
    _log(job, "Done.")
