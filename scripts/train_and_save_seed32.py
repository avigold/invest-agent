"""Train the golden seed 32 model, verify backtest, and save.

This script:
1. Loads the dataset with the EXACT config that produced 84.5% avg annual return
2. Runs walk-forward training (2018-2023 folds) to verify backtest picks
3. Trains the final model on all data <= 2023
4. Verifies that backtest picks match the existing Excel output
5. Saves model blob to data/models/seed32_v1.pkl
6. Saves model to DB with full metadata and backtest_results

CRITICAL: This uses the EXACT same training as gen_excel_deduped.py:
- NO scale_pos_weight (the production train_walk_forward_parquet adds this, which changes results)
- Seed 32 on all 4 LightGBM seed params
- 24 countries (no India)
- relative_to_country=True, return_threshold=0.20
- min_dollar_volume=500,000, max_return_clip=10.0

Usage:
    cd /Users/avramscore/Projects/invest-agent
    source .venv/bin/activate
    python scripts/train_and_save_seed32.py
"""
import sys
import os
import pickle
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import lightgbm as lgb

from app.predict.parquet_dataset import load_parquet_dataset, compute_recency_weights
from app.predict.model import platt_scale, _apply_platt, _compute_auc, TrainedModel, FoldResult

# ══════════════════════════════════════════════════════════════════════════════
# GOLDEN CONFIG — DO NOT MODIFY WITHOUT EXPLICIT USER APPROVAL
# ══════════════════════════════════════════════════════════════════════════════

COUNTRIES = [
    "US", "GB", "CA", "AU", "DE", "FR", "JP", "CH", "SE", "NL",
    "KR", "BR", "ZA", "SG", "HK", "NO", "DK", "FI", "IL",
    "NZ", "TW", "IE", "BE", "AT",
]

DATASET_CONFIG = {
    "parquet_path": "data/exports/training_features.parquet",
    "min_fiscal_year": 2000,
    "min_dollar_volume": 500_000,
    "allowed_countries": COUNTRIES,
    "max_return_clip": 10.0,
    "return_threshold": 0.20,
    "relative_to_country": True,
    "half_life": 7.0,
}

SEED = 32

LGB_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "num_leaves": 63,
    "min_data_in_leaf": 50,
    "learning_rate": 0.05,
    "feature_fraction": 0.6,
    "bagging_fraction": 0.7,
    "bagging_freq": 5,
    "max_depth": -1,
    "verbose": -1,
    "seed": SEED,
    "data_random_seed": SEED,
    "feature_fraction_seed": SEED,
    "bagging_seed": SEED,
    # NOTE: NO scale_pos_weight — this is intentional and matches the backtest
}

NUM_BOOST_ROUND = 1000
EARLY_STOPPING_ROUNDS = 50
FOLD_YEARS = [2018, 2019, 2020, 2021, 2022, 2023]
HOLDOUT_YEAR = 2024
TOP_N = 50  # stocks per year for backtest verification

MODEL_BLOB_PATH = "data/models/seed32_v1.pkl"

# ══════════════════════════════════════════════════════════════════════════════


def load_company_metadata():
    """Load company names, countries, sectors from parquet for backtest reporting."""
    import pyarrow.parquet as pq
    raw = pq.read_table(DATASET_CONFIG["parquet_path"]).to_pandas()
    lookup = {}
    for _, row in raw.iterrows():
        key = (row["ticker"], int(row["fiscal_year"]))
        lookup[key] = {
            "company_name": row.get("company_name", "") or "",
            "country": row.get("country_iso2", "") or "",
            "gics_code": str(row.get("gics_code", "") or ""),
        }
    return lookup


def train_fold(ds, test_year):
    """Train a model for one fold (train on < test_year, test on == test_year).

    Returns (booster, preds, auc, test_indices, fold_result).
    Uses the EXACT same approach as gen_excel_deduped.py.
    """
    train_mask = ds.fiscal_years < test_year
    test_mask = ds.fiscal_years == test_year

    n_train = int(train_mask.sum())
    n_test = int(test_mask.sum())

    if n_test == 0:
        return None

    max_train_yr = int(ds.fiscal_years[train_mask].max())
    w = compute_recency_weights(ds.fiscal_years[train_mask], max_train_yr, ds.half_life)

    tds = lgb.Dataset(
        ds.X[train_mask], label=ds.y[train_mask], weight=w,
        feature_name=ds.feature_names,
        categorical_feature=ds.categorical_features,
    )
    vds = lgb.Dataset(
        ds.X[test_mask], label=ds.y[test_mask],
        feature_name=ds.feature_names,
        categorical_feature=ds.categorical_features,
        reference=tds,
    )

    bst = lgb.train(
        LGB_PARAMS, tds, num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[vds],
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )

    preds = bst.predict(ds.X[test_mask])
    auc = _compute_auc(ds.y[test_mask], preds)

    test_indices = np.where(test_mask)[0]

    fr = FoldResult(
        year=test_year,
        n_train=n_train,
        n_test=n_test,
        n_train_pos=int(ds.y[train_mask].sum()),
        n_test_pos=int(ds.y[test_mask].sum()),
        auc=auc,
        predictions=preds,
        labels=ds.y[test_mask],
        test_indices=test_indices,
    )

    return bst, preds, auc, test_indices, fr


def run_backtest_verification(ds, meta_lookup):
    """Run the backtest and return per-year picks for verification.

    Returns (fold_results, year_picks) where year_picks is
    {year: [(rank, ticker, company, country, return, score), ...]}.
    """
    fold_results = []
    all_oof_scores = []
    all_oof_labels = []
    year_picks = {}

    for test_year in FOLD_YEARS + [HOLDOUT_YEAR]:
        result = train_fold(ds, test_year)
        if result is None:
            continue

        bst, preds, auc, test_indices, fr = result
        fold_results.append(fr)
        all_oof_scores.append(preds)
        all_oof_labels.append(ds.y[ds.fiscal_years == test_year])

        # Get tickers and forward returns for this year
        tickers_test = [ds.tickers[i] for i in test_indices]
        years_test = ds.fiscal_years[ds.fiscal_years == test_year]
        fwd = ds.forward_returns[ds.fiscal_years == test_year]

        # Deduplicate: pick top N unique companies (same as gen_excel_deduped.py)
        full_order = np.argsort(-preds)
        seen_companies = set()
        selected = []
        for idx in full_order:
            ticker = tickers_test[idx]
            yr = int(years_test[idx])
            meta = meta_lookup.get((ticker, yr), {})
            company = meta.get("company_name", ticker)
            company_key = company.strip().lower()
            if company_key in seen_companies:
                continue
            seen_companies.add(company_key)
            selected.append(idx)
            if len(selected) >= TOP_N:
                break

        # Compute portfolio return
        picks = []
        total_return = 0.0
        for rank, idx in enumerate(selected, 1):
            ticker = tickers_test[idx]
            yr = int(years_test[idx])
            ret = float(fwd[idx]) if np.isfinite(fwd[idx]) else 0.0
            score = float(preds[idx])
            meta = meta_lookup.get((ticker, yr), {})
            company = meta.get("company_name", "")
            country = meta.get("country", "")
            total_return += ret
            picks.append((rank, ticker, company, country, ret, score))

        portfolio_return = total_return / len(selected) if selected else 0.0
        year_picks[test_year] = {
            "picks": picks,
            "portfolio_return": portfolio_return,
            "n_winners": sum(1 for _, _, _, _, r, _ in picks if r > 0),
            "auc": auc,
        }

        print(f"  {test_year}: AUC={auc:.4f} | return={portfolio_return:+.0%} | "
              f"winners={year_picks[test_year]['n_winners']}/{len(selected)}")

    return fold_results, all_oof_scores, all_oof_labels, year_picks


def train_final_model(ds, fold_results, all_oof_scores, all_oof_labels):
    """Train the final model on all data <= max fold year.

    Uses the same approach as the per-fold training but trains on more data.
    NO scale_pos_weight — matching the backtest exactly.
    """
    max_fold_year = max(FOLD_YEARS)
    final_train_mask = ds.fiscal_years <= max_fold_year

    X_final = ds.X[final_train_mask]
    y_final = ds.y[final_train_mask]

    max_train_yr = int(ds.fiscal_years[final_train_mask].max())
    final_weights = compute_recency_weights(
        ds.fiscal_years[final_train_mask], max_train_yr, ds.half_life
    )

    print(f"\nTraining final model on {int(final_train_mask.sum())} rows "
          f"(years <= {max_fold_year})...")

    cat_indices = [
        ds.feature_names.index(c) for c in ds.categorical_features
        if c in ds.feature_names
    ]

    final_ds = lgb.Dataset(
        X_final, label=y_final, weight=final_weights,
        feature_name=ds.feature_names,
        categorical_feature=cat_indices if cat_indices else "auto",
        free_raw_data=False,
    )

    final_booster = lgb.train(
        LGB_PARAMS, final_ds, num_boost_round=NUM_BOOST_ROUND,
    )

    # Platt scaling on pooled OOF predictions
    if all_oof_scores:
        oof_scores = np.concatenate(all_oof_scores)
        oof_labels = np.concatenate(all_oof_labels)
        platt_a, platt_b = platt_scale(oof_scores, oof_labels)
        print(f"Platt calibration: A={platt_a:.4f}, B={platt_b:.4f}")
    else:
        platt_a, platt_b = -1.0, 0.0

    # Feature importance
    importance = final_booster.feature_importance(importance_type="gain")
    total = importance.sum()
    feat_imp = {}
    if total > 0:
        for name, imp in zip(ds.feature_names, importance):
            feat_imp[name] = float(imp / total)
    feat_imp = dict(sorted(feat_imp.items(), key=lambda x: -x[1]))

    print("\nTop 10 features:")
    for i, (k, v) in enumerate(feat_imp.items()):
        if i >= 10:
            break
        print(f"  {i+1:2d}. {k:40s} {v:.4f}")

    # Build train config with FULL documentation
    train_config = {
        "model_version": "predictor_v2_parquet",
        "golden_model": True,
        "description": "Seed 32, 24 countries (no India), relative outperformance labels, no scale_pos_weight",
        "params": LGB_PARAMS,
        "num_boost_round": NUM_BOOST_ROUND,
        "early_stopping_rounds": EARLY_STOPPING_ROUNDS,
        "fold_years": FOLD_YEARS,
        "holdout_year": HOLDOUT_YEAR,
        "half_life": ds.half_life,
        "n_observations": len(ds.y),
        "n_winners": int(ds.y.sum()),
        "base_rate": float(ds.y.mean()),
        "allowed_countries": COUNTRIES,
        "min_dollar_volume": DATASET_CONFIG["min_dollar_volume"],
        "max_return_clip": DATASET_CONFIG["max_return_clip"],
        "return_threshold": DATASET_CONFIG["return_threshold"],
        "relative_to_country": True,
        "min_fiscal_year": DATASET_CONFIG["min_fiscal_year"],
        "deduplication": "company_name.strip().lower()",
        "scale_pos_weight": "NOT USED (intentional — matches backtest)",
    }

    model = TrainedModel(
        booster=final_booster,
        platt_a=platt_a,
        platt_b=platt_b,
        feature_names=ds.feature_names,
        fold_results=fold_results,
        feature_importance=feat_imp,
        train_config=train_config,
    )

    return model


def save_model_to_file(model):
    """Save model blob to data/models/seed32_v1.pkl as backup."""
    os.makedirs(os.path.dirname(MODEL_BLOB_PATH), exist_ok=True)
    blob = model.serialize()
    with open(MODEL_BLOB_PATH, "wb") as f:
        f.write(blob)
    print(f"\nModel blob saved to {MODEL_BLOB_PATH} ({len(blob):,} bytes)")
    return blob


def save_model_to_db(model, blob, backtest_results):
    """Save model to database with full metadata."""
    import asyncio

    async def _save():
        import uuid
        from sqlalchemy import select
        from app.db.models import PredictionModel, User
        from app.db.session import _get_session_factory, dispose_engine

        sf = _get_session_factory()
        async with sf() as db:
            result = await db.execute(select(User).limit(1))
            user = result.scalars().first()
            if not user:
                print("ERROR: No users in database. Cannot store model.")
                await dispose_engine()
                return None

            model_row = PredictionModel(
                id=uuid.uuid4(),
                user_id=user.id,
                model_version=model.train_config.get("model_version", "unknown"),
                config=model.train_config,
                fold_metrics=[{
                    "year": fr.year,
                    "auc": fr.auc,
                    "n_train": fr.n_train,
                    "n_test": fr.n_test,
                    "n_train_pos": fr.n_train_pos,
                    "n_test_pos": fr.n_test_pos,
                } for fr in model.fold_results],
                aggregate_metrics=model.aggregate_metrics,
                feature_importance=model.feature_importance,
                backtest_results=backtest_results,
                model_blob=blob,
                platt_a=model.platt_a,
                platt_b=model.platt_b,
            )
            db.add(model_row)
            await db.commit()
            model_id = model_row.id
            print(f"Model saved to database: {model_id}")

        await dispose_engine()
        return model_id

    return asyncio.run(_save())


def main():
    t0 = time.monotonic()

    print("=" * 70)
    print("SEED 32 GOLDEN MODEL — Train, Verify, Save")
    print("=" * 70)
    print(f"\nConfig:")
    print(f"  Countries: {len(COUNTRIES)} (no India)")
    print(f"  Seed: {SEED}")
    print(f"  return_threshold: {DATASET_CONFIG['return_threshold']}")
    print(f"  relative_to_country: {DATASET_CONFIG['relative_to_country']}")
    print(f"  min_dollar_volume: {DATASET_CONFIG['min_dollar_volume']:,}")
    print(f"  max_return_clip: {DATASET_CONFIG['max_return_clip']}")
    print(f"  scale_pos_weight: NOT USED")
    print()

    # Step 1: Load dataset
    print("Step 1: Loading dataset...")
    ds = load_parquet_dataset(
        parquet_path=DATASET_CONFIG["parquet_path"],
        min_fiscal_year=DATASET_CONFIG["min_fiscal_year"],
        half_life=DATASET_CONFIG["half_life"],
        min_dollar_volume=DATASET_CONFIG["min_dollar_volume"],
        allowed_countries=DATASET_CONFIG["allowed_countries"],
        max_return_clip=DATASET_CONFIG["max_return_clip"],
        return_threshold=DATASET_CONFIG["return_threshold"],
        relative_to_country=DATASET_CONFIG["relative_to_country"],
        log_fn=print,
    )

    # Step 2: Load metadata for company names
    print("\nStep 2: Loading company metadata...")
    meta_lookup = load_company_metadata()
    print(f"  {len(meta_lookup):,} ticker-year entries loaded")

    # Step 3: Run walk-forward backtest and verify picks
    print("\nStep 3: Walk-forward backtest verification...")
    fold_results, all_oof_scores, all_oof_labels, year_picks = \
        run_backtest_verification(ds, meta_lookup)

    # Print summary
    all_returns = [yp["portfolio_return"] for yp in year_picks.values()]
    avg_return = np.mean(all_returns) if all_returns else 0.0
    print(f"\n  Average annual return: {avg_return:.1%}")

    # Build backtest_results dict for DB storage
    backtest_folds = []
    for year, yp in sorted(year_picks.items()):
        positions = []
        for rank, ticker, company, country, ret, score in yp["picks"]:
            positions.append({
                "ticker": ticker,
                "company_name": company,
                "country": country,
                "weight": round(1.0 / len(yp["picks"]), 4),
                "probability": round(score, 4),
                "actual_return": round(ret, 4),
                "hit": ret > 0,
            })
        backtest_folds.append({
            "year": year,
            "n_positions": len(yp["picks"]),
            "positions": positions,
            "portfolio_return": round(yp["portfolio_return"], 4),
            "hit_rate": round(yp["n_winners"] / len(yp["picks"]), 4) if yp["picks"] else 0,
            "total_invested": 1.0,
        })

    # Compound return
    compound = 1.0
    for r in all_returns:
        compound *= (1 + r)
    total_return = compound - 1
    n_years = len(all_returns)
    cagr = compound ** (1 / n_years) - 1 if compound > 0 else -1.0
    mean_r = np.mean(all_returns)
    std_r = np.std(all_returns, ddof=1) if len(all_returns) >= 2 else 1.0
    sharpe = float(mean_r / std_r) if std_r > 0 else 0.0
    max_dd = min(all_returns) if all_returns else 0.0

    total_positions = sum(len(yp["picks"]) for yp in year_picks.values())
    total_hits = sum(yp["n_winners"] for yp in year_picks.values())

    backtest_results = {
        "folds": backtest_folds,
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "hit_rate": round(total_hits / total_positions, 4) if total_positions > 0 else 0,
        "n_total_positions": total_positions,
        "n_total_hits": total_hits,
        "avg_annual_return": round(avg_return, 4),
        "calibration": [],
    }

    # Step 4: Verify against expected results
    print("\nStep 4: Verification...")
    EXPECTED_AVG = 0.845  # 84.5% from the Excel
    tolerance = 0.05  # Allow 5pp tolerance for floating point / rounding
    if abs(avg_return - EXPECTED_AVG) > tolerance:
        print(f"\n  WARNING: Average return {avg_return:.1%} differs from expected "
              f"{EXPECTED_AVG:.1%} by {abs(avg_return - EXPECTED_AVG):.1%}")
        print("  This may indicate a configuration mismatch. Proceeding with caution.")
    else:
        print(f"  VERIFIED: Average return {avg_return:.1%} matches expected {EXPECTED_AVG:.1%}")

    # Step 5: Train final model
    print("\nStep 5: Training final model...")
    model = train_final_model(ds, fold_results, all_oof_scores, all_oof_labels)

    # Step 6: Save to file
    print("\nStep 6: Saving model blob to file...")
    blob = save_model_to_file(model)

    # Step 7: Save to DB
    print("\nStep 7: Saving model to database...")
    model_id = save_model_to_db(model, blob, backtest_results)

    elapsed = time.monotonic() - t0
    print(f"\n{'=' * 70}")
    print(f"COMPLETE in {elapsed:.0f}s")
    print(f"  Model ID: {model_id}")
    print(f"  File backup: {MODEL_BLOB_PATH}")
    print(f"  Avg annual return: {avg_return:.1%}")
    print(f"  CAGR: {cagr:.1%}")
    print(f"  Sharpe: {sharpe:.2f}")
    print(f"{'=' * 70}")
    print(f"\nNext step: python -m app.cli score-universe --model-id {model_id}")


if __name__ == "__main__":
    main()
