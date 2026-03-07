# PRD 7.0 — Predictive Stock Scoring System

**Status**: In Progress
**Date**: 2026-03-05
**Depends on**: PRD 6.2 (Screener v2 — observations + forward returns)

## Problem

The v2 screener (PRD 6.2) labels historical observations as winners/non-winners and computes contrast features, but the contrast-based approach produces weak separation scores (< 0.12) because simple median comparisons don't capture non-linear, multi-feature interactions that distinguish 4x winners. We need a proper predictive system that:

1. Predicts which companies will 4x in the next few years
2. Identifies historical winners using only data available at the time (no look-ahead)
3. Scores predictions with a calibrated confidence index
4. Suggests portfolio allocation strategies, backtested against historical data

## Solution

LightGBM binary classification to predict "winner" observations (4x+ forward return). Trained via walk-forward cross-validation to prevent look-ahead bias. Probabilities calibrated via Platt scaling. Portfolio construction via quarter-Kelly position sizing with sector diversification constraints.

## Key Design Decisions

- **LightGBM over alternatives**: Handles missing values natively (critical — fundamentals are sparse for older observations), built-in feature importance, works well on small datasets (~2,000 obs), trains in seconds
- **Walk-forward CV over k-fold**: Respects temporal ordering — never trains on future data
- **Platt scaling over isotonic**: Monotonic guarantee, more stable with small calibration sets
- **Quarter-Kelly over full Kelly**: Safety margin — full Kelly is too aggressive for estimated probabilities
- **No scipy/sklearn dependency**: Platt scaling implemented in numpy (~30 lines)

## Data Foundation

Reuse existing `forward_scanner.py` `Observation` dataclass and `generate_observations()`. The observation unit (company x annual date with forward return label + trailing features) is exactly what we need for ML training.

## Feature Engineering — `app/predict/features.py`

22+ point-in-time features computed from monthly price data available at observation date.

### Price-derived (always available)

| Feature | Computation |
|---|---|
| `momentum_3m` | `price[t] / price[t-3] - 1` |
| `momentum_6m` | from Observation |
| `momentum_12m` | from Observation |
| `momentum_24m` | `price[t] / price[t-24] - 1` |
| `momentum_accel` | `momentum_6m - momentum_6m_lagged` |
| `relative_strength_12m` | `momentum_12m - index_momentum_12m` |
| `volatility_6m` | `stdev(monthly_returns[-6:]) * sqrt(12)` |
| `volatility_12m` | from Observation |
| `vol_trend` | `volatility_6m / volatility_12m` |
| `max_dd_12m` | from Observation |
| `max_dd_24m` | worst drawdown trailing 24 months |
| `ma_spread_10` | from Observation |
| `ma_spread_20` | `(price[t] - MA_20) / MA_20` |
| `price_range_12m` | `(high - low) / low` trailing 12m |
| `up_months_ratio_12m` | fraction of positive monthly returns |

### Cross-sectional (rank within cohort)

| Feature | Computation |
|---|---|
| `momentum_12m_rank` | percentile rank among all stocks at same date |
| `volatility_12m_rank` | percentile rank at same date |

### Fundamental (sparse)

| Feature | Source |
|---|---|
| `roe` | `fundamentals.roe` |
| `net_margin` | `fundamentals.net_margin` |
| `debt_equity` | `fundamentals.debt_equity` |
| `revenue_growth` | `fundamentals.revenue_growth` |
| `fcf_yield` | `fundamentals.fcf_yield` |

LightGBM handles NaN natively — no imputation needed.

## Model Training — `app/predict/model.py`

### Walk-Forward Cross-Validation

```
Fold 1: Train obs_date < 2015, test 2015
Fold 2: Train obs_date < 2016, test 2016
...
Fold 6: Train obs_date < 2020, test 2020
```

### Hyperparameters (conservative for small dataset)

- `num_leaves`: 15, `min_data_in_leaf`: 10, `learning_rate`: 0.05
- `feature_fraction`: 0.7, `bagging_fraction`: 0.7
- `num_boost_round`: 300, `early_stopping_rounds`: 30
- `scale_pos_weight`: auto (computed from class imbalance)

### Probability Calibration

Platt scaling: fit A, B in `P(y=1|f) = 1/(1+exp(A*f+B))` via Newton's method on held-out predictions.

## Backtesting — `app/predict/backtest.py` + `strategy.py`

### Position Sizing: Quarter-Kelly

`f = (p/|a| - q/b) * 0.25` where p=win probability, a=avg loss, b=avg win.

### Constraints

- Max single position: 10%
- Max sector: 30%
- Min probability: 5% to enter
- Annual rebalance

### Metrics

Hit rate, CAGR, Sharpe ratio, max drawdown, calibration by decile, feature importance.

## Confidence Tiers

| Tier | Probability |
|---|---|
| High | > 30% |
| Medium | 15-30% |
| Low | 5-15% |
| Negligible | < 5% |

## Storage

### `prediction_models` table

id, user_id, model_version, config (JSONB), fold_metrics (JSONB), aggregate_metrics (JSONB), feature_importance (JSONB), backtest_results (JSONB), model_blob (LargeBinary), platt_a, platt_b, created_at, job_id

### `prediction_scores` table

id, model_id, user_id, ticker, company_name, probability, confidence_tier, kelly_fraction, suggested_weight, contributing_features (JSONB), feature_values (JSONB), scored_at, job_id

## Jobs

- `prediction_train`: load universe → generate observations → build features → walk-forward train → backtest → score current → store
- `prediction_score`: re-score current universe using existing model

## API

```
GET  /v1/predictions/models
GET  /v1/predictions/models/{id}
GET  /v1/predictions/models/{id}/scores
DELETE /v1/predictions/models/{id}
```

## Frontend

- **Predictions.tsx**: Train config + models list (AUC, Sharpe, backtest return)
- **PredictionDetail.tsx**: Model metrics, fold table, feature importance, calibration, predictions table, portfolio allocation, backtest equity curve

## Files

| File | Action |
|---|---|
| `docs/product/prd_7_0.md` | New |
| `app/predict/__init__.py` | New |
| `app/predict/features.py` | New |
| `app/predict/dataset.py` | New |
| `app/predict/model.py` | New |
| `app/predict/backtest.py` | New |
| `app/predict/strategy.py` | New |
| `app/predict/scorer.py` | New |
| `app/jobs/handlers/prediction_train.py` | New |
| `app/jobs/handlers/prediction_score.py` | New |
| `app/jobs/handlers/__init__.py` | Modify |
| `app/api/routes_predictions.py` | New |
| `app/db/models.py` | Modify |
| `app/main.py` | Modify |
| `alembic/versions/0010_add_prediction_tables.py` | New |
| `pyproject.toml` | Modify |
| `web/src/pages/Predictions.tsx` | New |
| `web/src/pages/PredictionDetail.tsx` | New |
| `web/src/App.tsx` | Modify |
| `web/src/components/Sidebar.tsx` | Modify |
| `tests/test_features.py` | New |
| `tests/test_dataset.py` | New |
| `tests/test_model.py` | New |
| `tests/test_backtest.py` | New |

## Acceptance Criteria

1. Train a model from UI with default params → job completes with per-fold AUC logged
2. Model detail page shows walk-forward metrics, feature importance, calibration
3. Predictions table ranks companies by calibrated probability with confidence tiers
4. Backtest results show portfolio return, Sharpe, max drawdown vs benchmark
5. Existing screener pages continue to work unchanged
6. `pytest -q` passes, `npm run build` clean
