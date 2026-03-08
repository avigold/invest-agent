# PRD 9.4 — Full Composite Scoring for ML Picks & FMP Charts

**Product**: investagent.app
**Version**: 9.4
**Date**: 2026-03-08
**Status**: In Progress
**Priority**: HIGH

---

## Context

The ML system scores ~16k companies across 24 countries. The user wants the legacy deterministic system as a **secondary confirmation** — full composite scoring (country + industry + company) for every ML pick. The composite formula is: `country * 0.20 + industry * 0.20 + company * 0.60`, with Buy > 70, Sell < 40.

The Parquet feature_values contain every ratio the company sub-score needs (roe, net_margin, debt_equity, revenue_growth, eps_growth, fcf_yield, momentum_12m, max_dd_12m, ma_spread_20). Country and industry scores come from the existing deterministic pipeline.

Previously: country/industry scores only covered 10 countries. The ML golden config uses 24. This PRD expands coverage to all 24 countries.

## Model protection

This PRD does not modify any files in `app/predict/`.

**Rules:**
- Never delete or overwrite model files
- Never run SQL against `prediction_models`
- Never modify `model.py` serialise/deserialise without explicit user approval
- Never modify `scripts/gen_excel_deduped.py`

## Changes

### 1. Expand country config to 24 countries

`config/investable_countries_v1.json` — add 14 new countries (KR, BR, ZA, SG, HK, NO, DK, FI, IL, NZ, TW, IE, BE, AT) with equity index symbols verified against yfinance.

### 2. Expand GDELT FIPS mapping

`app/ingest/gdelt.py` — add 14 ISO2→FIPS entries to `_ISO2_TO_FIPS`.

### 3. Company sub-scores from feature_values

`app/score/feature_scorer.py` — `score_from_features()` pure function. Computes fundamental_score (6 ratios) and market_score (3 metrics), combines into company_score.

### 4. Full composite scoring in ML endpoints

`app/api/routes_predictions.py` — load country/industry scores from DB, combine with company sub-score using `RECOMMENDATION_WEIGHTS` (0.20/0.20/0.60). Add `deterministic_classification` to bulk scores, full breakdown to single-ticker endpoint.

### 5. FMP chart fallback

`app/api/routes_companies.py` — when Company DB row not found, fetch from FMP via `fetch_historical_prices()`.

### 6. Frontend

- `web/src/pages/MLPicks.tsx` — star badge from inline `deterministic_classification`
- `web/src/pages/MLStockDetail.tsx` — composite + country + industry + company score display

## Files changed

| File | Change |
|------|--------|
| `config/investable_countries_v1.json` | Add 14 countries |
| `app/ingest/gdelt.py` | Add 14 FIPS codes |
| `app/score/feature_scorer.py` | Create — company sub-score utility |
| `app/api/routes_predictions.py` | Full composite scoring |
| `app/api/routes_companies.py` | FMP chart fallback |
| `web/src/pages/MLPicks.tsx` | Inline classification for stars |
| `web/src/pages/MLStockDetail.tsx` | Composite score display |
| `tests/test_feature_scorer.py` | Tests |
| `tests/test_prediction_score_api.py` | Tests |

## Data population

After code changes, run:
1. `country_refresh` for all 24 countries (World Bank, IMF, GDELT, equity prices)
2. `industry_refresh` for all 24 countries (rubric evaluation, 11 sectors each)

## Verification

- [ ] Config has 24 country entries, GDELT has 24 FIPS mappings
- [ ] `country_scores` and `industry_scores` tables populated for all 24 countries
- [ ] Stars on ML Picks based on full composite (> 70 = Buy)
- [ ] ML stock detail shows composite + country + industry + company breakdown
- [ ] Chart serves FMP data for non-DB tickers
- [ ] `pytest -q` passes
- [ ] `npm run build` succeeds
