# PRD 9.1 — Re-score Universe, Clean Up ML Picks, Fix Fundamentals Performance

**Product**: investagent.app
**Version**: 9.1
**Date**: 2026-03-07
**Status**: Complete
**Priority**: HIGH

---

## Context

PRD 9.0 fixed the backend scoring and backtest logic to use top-50 equal weight, but the database still has old Kelly-based PredictionScore rows. The ML Picks page displays three columns (Confidence, Kelly, Weight) that are artifacts of the old system and mislead users. The Fundamentals page loads slowly because it lacks two-phase loading.

## Model protection — THIS IS NOT OPTIONAL

The model (`seed32_v1.pkl`, seed 32) produces 84.5% average annual return across 2018–2024. Users will make real investment decisions based on its output. If this model is deleted, corrupted, or overwritten, there is no guarantee it can be reproduced — the exact data snapshot, library versions, and random state that produced this result may not be recoverable.

PRD 9.1 changes are **frontend-only plus one operational step** (re-scoring). No files in `app/predict/` are modified. The `score-universe` CLI command loads the existing model **read-only** — it does not retrain, modify, or delete the model.

**Before re-scoring:**
- Verify DB model blob SHA-256 matches `data/models/seed32_v1.pkl`
- Verify `seed32_v1.pkl` matches `seed32_v1_backup.pkl`

**After re-scoring:**
- Verify DB model blob SHA-256 is unchanged

**Rules:**
- Never delete or overwrite model files
- Never run SQL against `prediction_models`
- Never modify `model.py` serialise/deserialise without explicit user approval
- Never modify `scripts/gen_excel_deduped.py`

## Changes

### 1. Re-score the universe

Run `python -m app.cli score-universe` to regenerate PredictionScore rows with corrected top-50 equal weight. The CLI deletes old scores for the model before inserting new ones (idempotent). No code changes — the logic was fixed in PRD 9.0.

**Pre-flight**: Verify model integrity before re-scoring (DB blob SHA-256 matches disk backup).

### 2. Clean up ML Picks table

**File**: `web/src/pages/MLPicks.tsx`

**Remove columns:**
- Confidence (`confidence_tier`) — arbitrary tiers that don't influence selection
- Kelly (`kelly_fraction`) — not used for portfolio construction
- Weight (`suggested_weight`) — always 2% for top 50, dash for rest; rank already conveys this

**Add column:**
- Portfolio — simple checkmark or "In Portfolio" badge for stocks ranked in top 50 (where `suggested_weight > 0`). Replaces Weight's useful signal (in/out) without implying variable sizing.

**Final columns (7):** #, Company, Country, Sector, Probability, Portfolio, Top Features

**Update stat cards:**
- Remove "Portfolio Util." card (always 100% with equal weight)
- Replace with "Portfolio" card: "Top 50 · 2% each"

**Shimmer loading for stat cards and country allocation:**
- Stat cards and country allocation section show shimmer/skeleton placeholders until the full dataset has loaded (i.e. `allScores` is populated, not just `firstPage`)
- Prevents displaying incorrect partial-data values during two-phase loading
- Use a simple pulsing `animate-pulse bg-gray-700/50 rounded` placeholder matching each card's dimensions

**Search placeholder:**
- Change search input placeholder from `"Search by ticker or company name..."` to `"Name | Symbol"`

**Clean up Score interface** — remove `confidence_tier`, `kelly_fraction` fields. Keep `suggested_weight` in the interface (used to determine portfolio membership) but don't display it as a column. Remove Kelly/Confidence sort options.

### 3. Fix Fundamentals page performance

**Problem**: `Recommendations.tsx` fetches ALL recommendations in one request. On cache miss, the user waits for the full dataset. ML Picks avoids this with two-phase loading (first page fast, full dataset in background).

**Frontend fix** (`web/src/pages/Recommendations.tsx`):
- On cache miss: fetch first page with `?limit=25` for instant display
- Fetch full dataset in background
- On cache hit: display cached data immediately (already works)
- Mirror the pattern from MLPicks.tsx (lines 75-131)

**Backend fix** (`app/api/routes_recommendations.py`):
- Add `limit: int | None` and `offset: int` query params to `GET /v1/recommendations`
- When `limit` is present, slice the results and return `{ "items": [...], "total": N }`
- When `limit` is absent, return bare array (backward compatible)

## Files changed

| File | Change |
|------|--------|
| `docs/product/prd_9_1.md` | Create — this PRD |
| `web/src/pages/MLPicks.tsx` | Remove Confidence/Kelly/Weight columns, add Portfolio indicator, update stat cards with shimmer loading, fix search placeholder, clean up sort options |
| `web/src/pages/Recommendations.tsx` | Add two-phase loading (first page fast, full in background) |
| `app/api/routes_recommendations.py` | Add `limit`/`offset` params to list endpoint |

## Files NOT changed

| File | Reason |
|------|--------|
| `app/predict/*` | All scoring logic fixed in PRD 9.0 — no predict files touched |
| `app/score/recommendations.py` | compute_recommendations is adequate; perf issue is frontend loading strategy |
| `data/models/*` | Model files never modified |
| `scripts/gen_excel_deduped.py` | Ground truth — never modified |

## Verification

- [ ] Model integrity verified before re-scoring (SHA-256 match)
- [ ] Re-score: 50 positions at 2% weight in DB
- [ ] Model integrity verified after re-scoring (unchanged)
- [ ] ML Picks: 7 columns, no Confidence/Kelly/Weight
- [ ] ML Picks: portfolio indicator visible for top 50
- [ ] ML Picks: stat cards show shimmer until full data loaded
- [ ] ML Picks: stat cards updated (no "Portfolio Util.")
- [ ] ML Picks: search placeholder reads "Name | Symbol"
- [ ] Fundamentals: first page appears instantly on cache miss
- [ ] Fundamentals: full dataset loads in background
- [ ] `npm run build` succeeds
- [ ] `pytest -q` passes
