# PRD 3.0 — Industry Module v1

**Product**: investagent.app
**Version**: 3.0 (incremental, builds on PRD 2.0)
**Date**: 2026-02-28
**Status**: Complete
**Milestone**: 3

---

## 1. What this PRD covers

This document specifies the Industry Module — a template-driven rubric scoring system that evaluates 11 GICS sectors against macro regime conditions from the Country Module. It describes the rubric configuration, scoring methodology, data model, decision packet structure, API endpoints, and frontend pages added in Milestone 3.

For the foundation, see [PRD 1.0](prd_1_0.md). For country data sources and scoring, see [PRD 2.0](prd_2_0.md).

## 2. Decisions made since PRD 2.0

| Open item from PRD 2.0 | Decision |
|-------------------------|----------|
| Frontend framework | **Migrated from Next.js to Vite + React Router** — Next.js SSR was unnecessary for SPA; Vite builds in ~600ms. FastAPI serves `web/dist/` in production via StaticFiles mount + SPA fallback. |
| Charting library | **Deferred again** — M3 uses tables, score cards, and signal indicators. Charts not yet needed. |
| Free tier quotas for industry | Not yet gated — `industry_refresh` runs without quota check for now. |

## 3. Industry universe

All 11 GICS sectors, evaluated per country in the investable universe (10 countries from M2). Total: up to 110 scored combinations per refresh.

| GICS Code | Sector |
|-----------|--------|
| 10 | Energy |
| 15 | Materials |
| 20 | Industrials |
| 25 | Consumer Discretionary |
| 30 | Consumer Staples |
| 35 | Health Care |
| 40 | Financials |
| 45 | Information Technology |
| 50 | Communication Services |
| 55 | Utilities |
| 60 | Real Estate |

## 4. Rubric configuration

The rubric is fully config-driven via `config/sector_macro_sensitivity_v1.json`. No hardcoded sector logic.

### 4.1 Macro indicators and thresholds

10 indicators from 5 data sources (all ingested in M2's country pipeline):

| Indicator | Threshold | Unit | Source |
|-----------|-----------|------|--------|
| `gdp_growth_pct` | 3.0 | % | World Bank |
| `inflation_pct` | 4.0 | % | World Bank |
| `unemployment_pct` | 6.0 | % | World Bank |
| `govt_debt_gdp_pct` | 60.0 | % | IMF WEO |
| `current_account_gdp_pct` | 0.0 | % | World Bank |
| `fdi_gdp_pct` | 2.0 | % | World Bank |
| `central_bank_rate_pct` | 4.0 | % | FRED (US proxy) |
| `hy_credit_spread_bps` | 400 | bps | FRED (US proxy) |
| `yield_curve_10y2y_bps` | 50 | bps | FRED (US proxy) |
| `stability_index` | 0.5 | 0–1 | GDELT DOC 2.0 |

### 4.2 Sector sensitivities

Each sector has 3–5 indicators. For each, the rubric specifies whether a value **above** or **below** the threshold is favorable:

| Sector | # Indicators | Key Sensitivities |
|--------|--------------|-------------------|
| Energy | 4 | GDP growth (high), inflation (high), current account (high), stability (high) |
| Materials | 4 | GDP growth (high), inflation (high), FDI (high), unemployment (low) |
| Industrials | 5 | GDP growth (high), unemployment (low), credit spreads (low), yield curve (high), FDI (high) |
| Consumer Disc. | 5 | GDP growth (high), unemployment (low), inflation (low), rates (low), credit spreads (low) |
| Consumer Staples | 3 | Inflation (low), stability (high), rates (low) |
| Health Care | 4 | Govt debt (low), stability (high), rates (low), GDP growth (high) |
| Financials | 5 | Yield curve (high), GDP growth (high), unemployment (low), credit spreads (low), stability (high) |
| Info Tech | 4 | GDP growth (high), rates (low), FDI (high), stability (high) |
| Comm. Services | 4 | GDP growth (high), rates (low), unemployment (low), stability (high) |
| Utilities | 4 | Rates (low), inflation (low), govt debt (low), stability (high) |
| Real Estate | 5 | Rates (low), GDP growth (high), unemployment (low), credit spreads (low), inflation (low) |

### 4.3 Signal evaluation

For each indicator in a sector:
- **Favorable**: value is on the good side of threshold → signal = `+1`
- **Unfavorable**: value is on the bad side of threshold → signal = `-1`
- **Missing**: no data available → signal = `0` (neutral)

Raw score = sum of all signals. Range: `[-N, +N]` where N = number of indicators.

## 5. Scoring methodology

### 5.1 Overview

Each industry×country combination receives a composite score (0–100) via percentile ranking across all 110 combinations. All scoring is deterministic, pinned to `calc_version = "industry_v1"`.

### 5.2 Pipeline

1. **Load macro data** for each country from `country_series_points` (latest value per series, mapped from series names to rubric indicator names)
2. **Evaluate rubric** for each country → 11 sector raw scores per country
3. **Percentile-rank** all 110 raw scores together (not per-sector, not per-country — all in one pass)
4. Scale to 0–100: `overall_score = percentile_rank × 100`

### 5.3 Why all 110 ranked together

Cross-country and cross-sector comparisons are meaningful. An Energy score in the US should be directly comparable to a Financials score in Japan. Ranking everything in one pool achieves this.

### 5.4 Risk detection

Threshold-based rules applied post-hoc (not part of the rubric):

| Risk type | Trigger | Severity |
|-----------|---------|----------|
| `macro_headwinds` | Overall score < 30 | high (< 15), medium (15–30) |
| `all_signals_negative` | Every active signal = -1 | high |

Risks are stored in `industry_risk_register` with industry_id, country_id, and detected_at.

## 6. Evidence chain

Same chain as Country Module (PRD 2.0):

```
Country series point (from M2 ingest)
  → IndustryScore.point_ids (references all points used)
    → IndustryScore.component_data (full rubric evaluation)
      → DecisionPacket (references score_ids)
```

The industry module does not ingest new data — it consumes the country module's stored data points. Evidence lineage traces back through country series points to artefacts.

## 7. New database tables

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `industries` | GICS sector registry | gics_code (unique), name |
| `industry_scores` | Scored industry×country combos | industry_id, country_id, as_of, calc_version, rubric_score, overall_score, component_data (JSONB), point_ids (JSONB) |
| `industry_risk_register` | Flagged risks | industry_id, country_id, risk_type, severity, description, detected_at |

Unique constraint on `industry_scores`: `(industry_id, country_id, as_of, calc_version)`.

## 8. Decision packets

### Industry packet structure

```json
{
  "gics_code": "40",
  "industry_name": "Financials",
  "country_iso2": "US",
  "country_name": "United States",
  "as_of": "2026-02-01",
  "calc_version": "industry_v1",
  "summary_version": "industry_summary_v1",
  "scores": {
    "overall": 75.5,
    "rubric": 3
  },
  "rank": 2,
  "rank_total": 110,
  "component_data": {
    "raw_score": 3,
    "max_possible": 5,
    "min_possible": -5,
    "signals": [
      {
        "indicator": "yield_curve_10y2y_bps",
        "value": 150,
        "threshold": 50,
        "favorable_when": "high",
        "signal": 1
      }
    ],
    "country_macro_summary": {
      "gdp_growth_pct": 2.1,
      "inflation_pct": 3.4
    }
  },
  "risks": [],
  "evidence": null
}
```

**Entity ID**: `uuid5(NAMESPACE_DNS, f"{industry.id}:{country.id}")` — deterministic, ensures idempotent upsert for the same industry×country pair.

## 9. New API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/v1/industries?iso2=XX` | Yes | Latest scores for all industry×country combos, sorted by overall_score desc. Optional country filter. |
| GET | `/v1/industry/{gics_code}/summary?iso2=XX&include_evidence=false` | Yes | Full decision packet for one industry×country pair. |

## 10. New job command

### `industry_refresh`

**Params** (JSONB):
- `iso2`: string or null (filter to one country, or all 10)
- `as_of`: date string or null (defaults to first of current month)

**Pipeline**:
1. Load rubric config, upsert Industry rows
2. Load countries (filtered by iso2 if provided)
3. Compute all industry scores (110 combos ranked together)
4. Delete old scores for same as_of + calc_version (idempotent)
5. Detect risks for each scored combo
6. Build decision packets
7. Commit; store packet IDs on job

**Classification**: Heavy job (uses concurrency slot)

## 11. Frontend pages

### Industry dashboard (`/industries`)
- Ranked table: rank, sector name, country, overall score, rubric score
- Country filter dropdown (dynamically populated from data)
- "Refresh Industries" button → submits `industry_refresh` job
- Each row links to industry detail page

### Industry detail (`/industries/{gics_code}?iso2=XX`)
- Score cards: overall (0–100 percentile), rubric (raw signal sum with max/min)
- Risk flags section with severity color-coding
- Macro Sensitivity Signals table: indicator, value, threshold, favorable_when, signal (+/−/?)
- Country Macro Context: the macro values used in evaluation
- Tier badge (Top/Mid/Bottom based on percentile position)
- Links back to Industries list and to Country detail page

### Dashboard update
- Top 5 industries preview on the main dashboard page

### Navigation
- "Industries" link added to NavBar

## 12. Acceptance criteria

- [x] `industry_refresh` job completes for all 110 combos
- [x] `GET /v1/industries` returns scored list sorted by overall desc
- [x] `GET /v1/industry/40/summary?iso2=US` returns a valid decision packet
- [x] All 11 GICS sectors are scored per country
- [x] Rubric evaluation is deterministic (same inputs → same outputs)
- [x] Missing indicators contribute 0 (neutral) to raw score
- [x] Percentile ranking ranks all 110 combos in one pass
- [x] Risk detection flags low-scoring combos
- [x] Industries table and detail pages render correctly
- [x] All tests pass (`pytest -q` — 98 tests including 13 industry-specific)

## 13. Known limitations

- **FRED indicators are US-centric**: Central bank rates, HY spreads, and yield curve are US-specific from FRED. Non-US countries see missing data (neutral signal) for these indicators until a global rates/spreads source is added.
- **Equal indicator weights**: All indicators within a sector contribute equally (±1). Per-indicator weights could be added in a future rubric version.
- **Risk thresholds hardcoded**: The 30-point macro_headwinds threshold is in Python code, not in the rubric config. Could be moved to config for consistency.
- **No evidence endpoint**: Industry packets don't expose `include_evidence=true` with artefact-level lineage (evidence field is always null). The point_ids on IndustryScore provide the link, but the packet builder doesn't hydrate it into the response.

## 14. Updated open items

### Resolved
- [x] Frontend framework: Migrated to Vite + React Router
- [x] Industry rubric design: Config-driven JSON with 11 sectors and 10 macro indicators

### Still open
- [ ] Charting library (Recharts vs D3)
- [ ] Pro tier pricing
- [ ] Free tier quotas for industry/company commands
- [ ] Per-indicator weights in rubric (currently all equal)
- [ ] Global rates/spreads data source for non-US countries
