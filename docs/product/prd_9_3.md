# PRD 9.3 — ML Stock Detail Page & Cross-System Agreement Flag

**Product**: investagent.app
**Version**: 9.3
**Date**: 2026-03-08
**Status**: Draft
**Priority**: HIGH

---

## Context

ML Picks shows ~16k scored stocks but tickers are not clickable — the link was removed (PRD 9.1) because clicking led to `/companies/:ticker` which requires a deterministic DecisionPacket (only 136 companies have one). Meanwhile, the ML system already stores all 186 feature values per stock in the `PredictionScore.feature_values` JSONB column. Rather than expanding the deterministic pipeline to cover 16k companies, we build a detail page directly from the ML data and show deterministic scores alongside when they exist.

The user also wants to flag stocks where both systems agree — a star in the ML Picks table for stocks that are also classified "Buy" by the deterministic system.

## Model protection

This PRD does not modify any files in `app/predict/`. It adds read-only API endpoints and frontend pages.

**Rules:**
- Never delete or overwrite model files
- Never run SQL against `prediction_models`
- Never modify `model.py` serialise/deserialise without explicit user approval
- Never modify `scripts/gen_excel_deduped.py`

## Changes

### 1. Backend: New endpoint `GET /v1/predictions/score/{ticker}`

**File**: `app/api/routes_predictions.py`

Returns the ML score for a single ticker with full feature values, plus deterministic classification if available.

Response shape:
```json
{
  "ticker": "AAPL",
  "company_name": "Apple Inc.",
  "country": "US",
  "sector": "Information Technology",
  "probability": 0.544,
  "suggested_weight": 0.02,
  "contributing_features": { "...top 5..." },
  "feature_values": { "...all ~186..." },
  "scored_at": "2026-03-08T...",
  "model_id": "...",
  "model_version": "seed32_v1",
  "fundamentals": {
    "classification": "Buy",
    "composite_score": 72.3,
    "company_score": 68.5,
    "country_score": 75.0,
    "industry_score": 71.2
  }
}
```

- `fundamentals` is `null` when the stock has no deterministic score (most of the 16k)
- Queries `PredictionScore` for ticker from the user's latest model
- Calls `compute_recommendations(db)` to find the deterministic classification
- Returns 404 if ticker not found in ML scores

### 2. Backend: Chart endpoint yfinance fallback

**File**: `app/api/routes_companies.py`

The `/v1/company/{ticker}/chart` endpoint currently returns 404 if the ticker has no `Company` row in the DB. Add a yfinance fallback: when `Company` is not found, fetch price history directly from yfinance (the same library already used elsewhere in the codebase) and return the same response shape. This enables the stock chart on the ML detail page for all ~16k tickers.

### 3. Frontend: ML Picks star badge + restore link

**File**: `web/src/pages/MLPicks.tsx`

- On mount, fetch `/v1/recommendations` and build a `Set<string>` of tickers with `classification === "Buy"`
- For each row in the table, if the ticker is in the Buy set, render a gold star icon before the ticker name
- Star has a CSS tooltip: "Also recommended Buy by Fundamentals scoring"
- Restore ticker as `<Link to={/ml/picks/${s.ticker}}>` (was removed in PRD 9.1)

### 4. Frontend: New page `MLStockDetail`

**File**: `web/src/pages/MLStockDetail.tsx` (new)
**Route**: `/ml/picks/:ticker` in `web/src/App.tsx`

Sections:

1. **Header** — Company name + ticker badge, ML probability (large, colour-coded), "In Portfolio" badge, agreement flag ("Both systems agree — Buy" when deterministic also says Buy)

2. **Stock Chart** — Reuse `StockChart` component

3. **ML Score** — Probability with colour bar, top 5 contributing features with importance percentages

4. **Deterministic Scores** (when available) — Overall / Fundamental / Market score cards via `ScoreCard` component, classification badge. When not available: grey card "Not scored by Fundamentals system"

5. **Feature Values** — Grouped by category, collapsible sections:

| Category | Features | Default |
|----------|----------|---------|
| Profitability & Returns | `roe`, `roa`, `roic`, `net_margin`, `gross_margin`, `ebitda_margin`, `operating_margin`, `roe_change`, `earnings_quality`, `accruals_ratio`, `effective_tax_rate`, `margin_expansion`, `piotroski_f_score` | Open |
| Growth | `revenue_growth`, `net_income_growth`, `operating_income_growth`, `gross_profit_growth`, `eps_growth`, `fcf_growth` | Open |
| Capital Structure | `debt_equity`, `debt_assets`, `net_debt_ebitda`, `interest_coverage`, `current_ratio`, `cash_ratio`, `cash_conversion`, `fcf_to_net_income`, `dividend_payout`, `buyback_yield`, `capex_to_*`, `rd_to_revenue`, `sbc_to_revenue` | Open |
| Market & Technical | `momentum_*`, `volatility_*`, `max_dd_*`, `price_range_*`, `distance_from_*`, `ma_spread_*`, `up_months_ratio_*`, `avg_daily_volume_*`, `dollar_volume_*` | Open |
| Turnover | `inventory_turnover`, `asset_turnover`, `receivables_turnover` | Open |
| Balance Sheet | `bal_*` (56 items) | Collapsed |
| Income Statement | `inc_*` (33 items) | Collapsed |
| Cash Flow | `cf_*` (27 items) | Collapsed |

Feature labels are humanised (underscores → spaces, prefixes stripped for section context). Values formatted contextually — percentages for ratios, currency-like for absolute values, plain numbers otherwise.

## Files changed

| File | Change |
|------|--------|
| `docs/product/prd_9_3.md` | Create — this PRD |
| `app/api/routes_predictions.py` | Add `GET /v1/predictions/score/{ticker}` endpoint |
| `app/api/routes_companies.py` | Add yfinance fallback to chart endpoint |
| `web/src/pages/MLStockDetail.tsx` | Create — ML stock detail page |
| `web/src/pages/MLPicks.tsx` | Add star badge, restore ticker link |
| `web/src/App.tsx` | Add route `/ml/picks/:ticker` |
| `tests/test_routes_predictions.py` | Add test for single-ticker endpoint |

## Files NOT changed

| File | Reason |
|------|--------|
| `app/predict/parquet_scorer.py` | Scoring logic untouched |
| `app/predict/model.py` | Model untouched |
| `scripts/gen_excel_deduped.py` | Ground truth — never modified |
| `data/models/*` | Model files never modified |

## Verification

- [ ] `GET /v1/predictions/score/AAPL` returns full feature_values + fundamentals
- [ ] `GET /v1/predictions/score/NONEXIST` returns 404
- [ ] Chart endpoint works for non-DB tickers via yfinance fallback
- [ ] ML Picks: star on stocks also classified "Buy" in Fundamentals
- [ ] ML Picks: star tooltip explains cross-system agreement
- [ ] ML Picks: clicking ticker navigates to `/ml/picks/AAPL`
- [ ] ML Stock Detail: shows ML probability, contributing features
- [ ] ML Stock Detail: features grouped by category with collapsible sections
- [ ] ML Stock Detail: shows deterministic scores when available
- [ ] ML Stock Detail: "Not scored" message when no deterministic data
- [ ] ML Stock Detail: stock chart renders for any ticker
- [ ] ML Stock Detail: agreement badge when both systems say Buy
- [ ] `pytest -q` passes
- [ ] `npm run build` succeeds
