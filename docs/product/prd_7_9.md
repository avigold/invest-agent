# PRD 7.9 — ML-First Platform Rework

## Problem

The ML relative outperformance model (PRD 7.7-7.8) averages 84.5%/year across 7 backtested years (2018-2024) with company deduplication, seed 32. Even the worst seed across 100 trials averages +52%/year. This massively outperforms the composite scoring system. The platform should center on the ML approach as the primary signal.

Additionally, the scoring pipeline produces duplicate entries for the same company listed on multiple exchanges (e.g. NVIDIA appears as NVDA, NVD.DE, NVD.F, NVDA.NE), wasting portfolio slots. Country and sector data are buried in JSONB instead of being proper columns.

## Solution

1. Add `country` and `sector` columns to PredictionScore for direct access
2. Add company deduplication to the scoring pipeline
3. Remove India from default allowed countries (impractical small-caps)
4. Promote ML Picks to primary signal in navigation
5. Replace Dashboard "Top Buy Recommendations" with top ML picks
6. Keep composite scoring demoted but accessible

## Changes

### Database
- Add `country VARCHAR` and `sector VARCHAR` nullable columns to `prediction_scores` table
- Alembic migration

### Backend
- `app/db/models.py` — Add columns to PredictionScore model
- `app/predict/parquet_scorer.py` — Add `deduplicate` parameter; skip duplicate company names, keep highest-scored listing
- `app/cli.py` — Update score_universe to populate country/sector columns and use deduplication
- `app/api/routes_predictions.py` — Include country and sector in all score API responses

### Frontend
- `web/src/components/NavBar.tsx` — Reorder Signals: ML Picks, Models, Recommendations, Screener
- `web/src/pages/Dashboard.tsx` — Replace composite recommendations with ML picks from latest model
- `web/src/pages/MLPicks.tsx` — Read country/sector from direct fields (fallback to contributing_features), add sector column

### Tests
- `tests/test_parquet_scorer.py` — Add deduplication tests

## Files

| File | Action |
|------|--------|
| `docs/product/prd_7_9.md` | New |
| `alembic/versions/xxx_add_country_sector.py` | New migration |
| `app/db/models.py` | Modify |
| `app/predict/parquet_scorer.py` | Modify |
| `app/cli.py` | Modify |
| `app/api/routes_predictions.py` | Modify |
| `web/src/components/NavBar.tsx` | Modify |
| `web/src/pages/Dashboard.tsx` | Modify |
| `web/src/pages/MLPicks.tsx` | Modify |
| `tests/test_parquet_scorer.py` | Modify |

## Acceptance

1. `alembic upgrade head` applies cleanly
2. `pytest -q` passes
3. `python -m app.cli score-universe` deduplicates by company, populates country/sector columns
4. Dashboard shows top ML picks (not composite recommendations)
5. Nav: ML Picks first in Signals group
6. No duplicate companies in scored universe
