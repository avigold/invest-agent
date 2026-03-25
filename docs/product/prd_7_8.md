# PRD 7.8 — Score Universe + Portfolio Construction + Multi-Tier Nav

**Status**: Complete
## Problem

The relative outperformance model (PRD 7.7) is trained and validated — mean AUC 0.5989, monotonic decile returns, avg +85%/yr on top 50 in backtest. But it only exists as a trained blob in the database with no stocks scored. The existing scoring pipeline (`scorer.py`, `strategy.py`) serves the deterministic recommendation system and must not be modified. The ML pipeline needs its own standalone infrastructure.

Additionally, the navigation bar has 7 flat links and will become crowded as features grow.

## Solution

1. **Standalone ML scorer** — `parquet_scorer.py` scores from the Parquet export with its own Kelly constants and portfolio constraints, completely independent of the deterministic pipeline.
2. **Multi-tier navigation** — 3 dropdown groups (Research, Signals, System) replace the flat nav.
3. **ML Picks page** — New page showing the scored universe with portfolio weights.

## Changes

### `app/predict/parquet_scorer.py` (New)

Standalone scorer with own constants:
- `ML_AVG_WIN = 0.42`, `ML_AVG_LOSS = -0.15` (relative outperformance economics)
- `ML_KELLY_FRACTION = 0.25`, position/country/sector caps
- `score_from_parquet()`: loads Parquet, takes most recent year per ticker, predicts via model, applies Kelly + constraints
- No imports from `scorer.py` or `strategy.py`

### `app/cli.py` (Modify)

New `score-universe` command: loads model from DB, calls `score_from_parquet()`, stores PredictionScore rows.

### `app/api/routes_predictions.py` (Modify)

Add `GET /v1/predictions/models/latest/scores` convenience endpoint.

### `web/src/components/NavBar.tsx` (Rewrite)

3 dropdown groups: Research (Countries, Industries, Companies), Signals (Recommendations, Screener, ML Picks, Models), System (Jobs, Admin).

### `web/src/App.tsx` (Modify)

Add `/ml/picks` and `/ml/models` routes. Keep `/predictions` as alias.

### `web/src/pages/MLPicks.tsx` (New)

Scored universe page: summary cards, sortable table (rank, ticker, country, probability, Kelly, weight), country breakdown.

### `tests/test_parquet_scorer.py` (New)

Tests for feature alignment, Kelly fractions, country/position caps.

## Files

| File | Action |
|------|--------|
| `docs/product/prd_7_8.md` | Update |
| `app/predict/parquet_scorer.py` | New |
| `app/cli.py` | Modify |
| `app/api/routes_predictions.py` | Modify |
| `web/src/components/NavBar.tsx` | Rewrite |
| `web/src/App.tsx` | Modify |
| `web/src/pages/MLPicks.tsx` | New |
| `tests/test_parquet_scorer.py` | New |

## Verification

1. `pytest -q` — all tests pass
2. `python -m app.cli score-universe` — scores universe, stores PredictionScore rows
3. Nav has 3 dropdown groups
4. `/ml/picks` shows scored stocks with weights
5. No country >30% of portfolio weight
