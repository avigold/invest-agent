# PRD 7.5 — ML Model Training Pipeline

## Problem

We have a comprehensive training dataset (PRD 7.4): 771,394 rows × 199 columns covering 43,291 companies across 100 countries and 44 fiscal years. The dataset includes ~140 raw FMP financial fields, ~40 derived ratios, ~25 price features, forward return labels, and context features. Class distribution: 8.6% "winner" (12m return ≥ 100%), 85.8% "normal".

The existing `app/predict/` module has a complete LightGBM pipeline — walk-forward CV, Platt scaling, backtesting — but was built for a small dataset (~2,000 observations, 22 features). We need to extend it to train on the comprehensive Parquet export (~180 features, ~600k labeled rows).

## Key Challenges

1. **Temporal integrity**: Walk-forward validation with strict no-leakage guarantee
2. **Recency weighting**: Market forces change over time — older data should have less influence
3. **Class imbalance**: 10:1 normal-to-winner ratio
4. **Known limitations**: No news/sentiment data (reactive investor behavior not captured), survivorship bias (only companies currently in DB)

## Solution

### Extend `app/predict/` with Parquet-aware training

Add `parquet_dataset.py` for data loading alongside existing `dataset.py`. Extend `model.py` with `train_walk_forward_parquet()` that adds recency weighting and handles the larger feature set.

### Data Preprocessing

1. Read Parquet via PyArrow → pandas
2. Filter: `fiscal_year >= 2000` and `fwd_label IS NOT NULL`
3. Drop non-feature columns (identifiers, targets, always-null)
4. Encode categoricals: `gics_code` → int (0-11), `country_iso2` → int (0-99), declared as LightGBM categorical
5. Build labels: winner=1, normal=0
6. ~182 numeric features, NaN stays as NaN (LightGBM native handling)

### Recency Weighting

Exponential half-life decay: `weight(year) = 0.5 ^ ((max_train_year - year) / half_life)`

Default half-life = 7 years. Weights recomputed per fold so the most recent training data always gets weight 1.0.

### Walk-Forward Validation

| Fold | Train | Test | ~Train rows | ~Test rows |
|------|-------|------|-------------|------------|
| 1 | ≤2017 | 2018 | 350k | 37k |
| 2 | ≤2018 | 2019 | 390k | 40k |
| 3 | ≤2019 | 2020 | 430k | 41k |
| 4 | ≤2020 | 2021 | 470k | 42k |
| 5 | ≤2021 | 2022 | 510k | 42k |
| 6 | ≤2022 | 2023 | 550k | 42k |
| Holdout | ≤2023 | 2024 | 590k | 37k |

### Hyperparameters (tuned for larger dataset)

- num_leaves: 63 (was 15), min_data_in_leaf: 50 (was 10)
- learning_rate: 0.05, feature_fraction: 0.6, bagging_fraction: 0.7
- num_boost_round: 1000 (was 300), early_stopping: 50 rounds
- scale_pos_weight: computed from class ratio (~10)

### Evaluation

- Per-fold: AUC, precision@100/500/1000
- Aggregate: mean/std/min/max AUC
- Holdout: AUC, precision@K, calibration analysis
- Feature importance: gain-based, normalized, top 20 logged

## Files

| File | Action |
|------|--------|
| `docs/product/prd_7_5.md` | New |
| `app/predict/parquet_dataset.py` | New — Parquet loading, preprocessing, recency weights |
| `app/predict/model.py` | Modify — add `train_walk_forward_parquet()`, precision@K |
| `app/cli.py` | Modify — add `train-model`, `evaluate-model` commands |
| `tests/test_parquet_dataset.py` | New |
| `tests/test_model_training.py` | New |

## CLI

```
python -m app.cli train-model [--half-life 7.0] [--holdout-year 2024] [--min-fiscal-year 2000]
python -m app.cli evaluate-model [--model-id UUID] [--year 2024]
```

## Acceptance Criteria

1. `pytest -q` passes (existing + new tests)
2. `train-model` completes, logs per-fold AUC > 0.55
3. Holdout AUC and precision@K reported
4. Feature importance shows interpretable top features
5. Model stored in `PredictionModel` table
