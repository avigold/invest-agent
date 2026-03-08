# PRD 9.7 — Make Train Model Feature Use ML/Parquet System

## Problem

The Predictions page train form uses the **deterministic scoring system** (22 features, ~136 companies from the DB). It should use the **ML/Parquet system** (186 features, ~771k rows from Parquet export) which produced the validated 84.5% backtest. The form exposes 4 irrelevant parameters; defaults should match the golden model config (seed 32).

## Solution

Rewrite the `prediction_train` job handler to use the parquet pipeline, and update the frontend form to expose all relevant parameters with golden defaults.

## Parameters (with golden defaults)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `seed` | 32 | Random seed (all 4 LightGBM seeds) |
| `countries` | 24 codes (no India) | `US,GB,CA,AU,DE,FR,JP,CH,SE,NL,KR,BR,ZA,SG,HK,NO,DK,FI,IL,NZ,TW,IE,BE,AT` |
| `min_dollar_volume` | 500,000 | Min 30-day avg dollar volume |
| `max_return_clip` | 10.0 | Clip extreme 12m returns |
| `return_threshold` | 0.20 | Excess return threshold (relative to country) |
| `relative_to_country` | true | Label by excess over country-year median |
| `half_life` | 7.0 | Recency weighting half-life (years) |
| `min_fiscal_year` | 2000 | Earliest fiscal year to include |
| `num_leaves` | 63 | LightGBM complexity |
| `fold_years` | 2018-2023 | Walk-forward CV test years |
| `holdout_year` | 2024 | Holdout evaluation year |

Hardcoded (not exposed): `learning_rate` (0.05), `feature_fraction` (0.6), `bagging_fraction` (0.7), `bagging_freq` (5), `num_boost_round` (1000), `early_stopping_rounds` (50), `parquet_path` (fixed).

## Golden Model Protections

1. **Always create new** — NEW `PredictionModel` row. Never update/delete existing.
2. **Score isolation** — `PredictionScore` rows keyed by new model_id. Golden model scores untouched.
3. **No cascade deletes** — never DELETE from `prediction_models` or `prediction_scores` for other models.
4. **Safe file backup** — `data/models/{version}_{id_prefix}.pkl`. Never overwrite `seed32_v1.pkl` or `seed32_v1_backup.pkl`.
5. **Config immutability** — copy `PARQUET_PARAMS` dict, never mutate the constant.
6. **Full config audit** — complete config logged to job log AND model's `config` JSONB field.
7. **Parquet read-only** — training data only read, never modified.

## Job Handler Flow

1. Parse params, log full config
2. `load_parquet_dataset()` — load + filter parquet data
3. `train_walk_forward_parquet()` — walk-forward CV training
4. `run_backtest()` — backtest on fold results
5. `score_from_parquet()` — score current universe
6. Create NEW `PredictionModel` row
7. Create NEW `PredictionScore` rows
8. Save model blob to `data/models/` (safe naming)

## Files Modified

| File | Change |
|------|--------|
| `app/jobs/handlers/prediction_train.py` | Rewrite with parquet pipeline |
| `web/src/pages/Predictions.tsx` | Rewrite form with golden defaults |

## Acceptance Criteria

- Training job from UI uses parquet system (job log shows ~771k rows, 186 features)
- Default params match golden model config exactly
- Golden model's PredictionModel row, PredictionScore rows, and disk files untouched after new training
- `npm run build` succeeds
