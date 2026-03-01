# PRD 5.1 — Continuous Industry Scoring

**Product**: investagent.app
**Version**: 5.1 (incremental, builds on PRD 5.0)
**Date**: 2026-03-01
**Status**: Complete
**Milestone**: 5

---

## 1. What this PRD covers

This document specifies the replacement of binary industry rubric scoring with continuous `absolute_score()` per indicator. The binary +1/-1 signal system produced extremely coarse scores (only 5-11 distinct values per sector) and systematically depressed industry scores, suppressing Buy recommendations across the entire pipeline.

For the original industry rubric design, see [PRD 3.0](prd_3_0.md). For absolute scoring methodology, see [PRD 5.0 §6.4](prd_5_0.md).

## 2. Problem statement

### 2.1 Coarse scoring

With 3-5 indicators per sector and binary +1/-1 signals, each sector could only produce N*2+1 distinct raw scores (e.g., 5 indicators → 11 values: -5 through +5). After linear rescale to 0-100, this meant scores clustered at fixed intervals (0, 10, 20, ..., 100).

### 2.2 Cliff effects

The binary threshold comparison created 100-point cliffs at arbitrary boundaries. GDP growth of 2.79% scored identically to 0% (both below 3.0% threshold → -1), while 3.01% got +1. A 0.22% difference in GDP growth produced a 100-point swing in signal contribution.

### 2.3 Downstream impact

Industry scores averaged 43.7/100 across all 110 country×sector combinations. At 20% weight in the recommendation composite (20% country + 20% industry + 60% company), this depressed composite scores and produced only 1 Buy recommendation out of 148 companies.

| Score bucket | Count (of 110) |
|---|---|
| 0 | 4 |
| 1-25 | 19 |
| 26-50 | 51 |
| 51-75 | 30 |
| 76-100 | 6 |

## 3. Solution: continuous scoring per indicator

Replace binary threshold comparison with `absolute_score()` per indicator, using the same function already proven in country and company scoring (PRD 5.0 §6.4).

### 3.1 Key design decisions

| Decision | Detail |
|---|---|
| Scoring function | Reuse existing `absolute_score(value, floor, ceiling, higher_is_better)` from `app/score/absolute.py` |
| Direction per indicator | Determined by the rubric's `favorable_when` field per sector — NOT hardcoded in threshold config. The same indicator (e.g., inflation) can be `higher_is_better=True` for Energy but `higher_is_better=False` for Consumer Discretionary. |
| Thresholds location | New `INDUSTRY_INDICATOR_THRESHOLDS` dict in `app/score/versions.py` — floor/ceiling only, no `higher_is_better` |
| Rubric config | **Unchanged** — `config/sector_macro_sensitivity_v1.json` still defines which indicators per sector and their `favorable_when` direction. Domain knowledge preserved. |
| Aggregation | Weighted average of indicator scores → sector overall (0-100). Currently all weights = 1 (equal weighting). |

### 3.2 Industry indicator thresholds

New `INDUSTRY_INDICATOR_THRESHOLDS` dict — floor/ceiling only:

| Series name | Floor (→0) | Ceiling (→100) | Notes |
|---|---|---|---|
| `gdp_growth` | -2.0 | 8.0 | Same as macro |
| `inflation` | 1.0 | 15.0 | Same as macro |
| `unemployment` | 2.0 | 15.0 | Same as macro |
| `govt_debt_gdp` | 20.0 | 200.0 | Same as macro |
| `current_account_gdp` | -8.0 | 10.0 | Same as macro |
| `fdi_gdp` | -1.0 | 8.0 | Same as macro |
| `fedfunds` | 0.0 | 10.0 | 0% = zero lower bound, 10% = restrictive |
| `hy_spread` | 200.0 | 1000.0 | 200bps = tight, 1000bps = distress (in bps) |
| `yield_curve` | -100.0 | 300.0 | -100bps = inverted, +300bps = steep (in bps) |
| `stability` | 0.0 | 1.0 | Already 0-1 by construction |

### 3.3 Scoring example

US Info Tech with GDP growth 2.79%:

**Before (binary)**: 2.79% < 3.0% threshold → signal = -1 → contributes -1 to raw score

**After (continuous)**: `absolute_score(2.79, -2.0, 8.0, higher_is_better=True)` = 47.9 → contributes 47.9 to weighted average

A 0.22% increase to 3.01% now changes the score by 2.2 points (47.9 → 50.1) instead of a 100-point cliff.

## 4. Signal data structure

### Before (PRD 3.0)

```json
{
  "indicator": "gdp_growth_pct",
  "value": 2.79,
  "threshold": 3.0,
  "favorable_when": "high",
  "signal": -1
}
```

### After

```json
{
  "indicator": "gdp_growth_pct",
  "value": 2.79,
  "favorable_when": "high",
  "score": 47.9,
  "floor": -2.0,
  "ceiling": 8.0
}
```

Missing data signals include `"reason": "missing_data"` and score 50.0 (neutral).

## 5. Scoring pipeline changes

### 5.1 `evaluate_rubric()` (rewritten)

For each sector's sensitivity:
1. Look up `floor`/`ceiling` from `INDUSTRY_INDICATOR_THRESHOLDS` via `_INDICATOR_TO_SERIES` mapping
2. Determine `higher_is_better` from `favorable_when` in the rubric config
3. Call `absolute_score(value, floor, ceiling, higher_is_better)` → 0-100
4. Weighted average of all indicator scores → `raw_score` (0-100)

Returns `raw_score` in [0, 100], `max_possible: 100`, `min_possible: 0`.

### 5.2 `compute_industry_scores()` (simplified)

The linear rescale `((raw_score + N) / (2*N)) * 100` is removed. `evaluate_rubric()` returns 0-100 directly, so `overall = raw_score`.

The `rubric_score` DB column is set equal to `overall_score` (both are the continuous 0-100 value).

### 5.3 `detect_industry_risks()` (updated)

| Risk type | Old trigger | New trigger |
|---|---|---|
| `macro_headwinds` | overall < 30 | overall < 30 (unchanged) |
| `all_signals_negative` | all active `signal == -1` | all indicator `score < 30` |

## 6. Version bump

| Constant | Old | New |
|---|---|---|
| `INDUSTRY_CALC_VERSION` | `"industry_v2"` | `"industry_v3"` |
| `INDUSTRY_SUMMARY_VERSION` | `"industry_summary_v2"` | `"industry_summary_v3"` |

Old v2 scores are ignored by API queries that filter on `calc_version`.

## 7. API changes

### `GET /v1/industries`

- Removed `rubric_score` field from response items (was the raw +/-N integer; now redundant with `overall_score`)

### `GET /v1/industry/{gics_code}/summary`

- `scores` object: removed `rubric` key (was the raw +/-N integer)
- `component_data.signals`: new structure with `score`/`floor`/`ceiling` instead of `threshold`/`signal`
- `component_data.max_possible`: now 100 (was N)
- `component_data.min_possible`: now 0 (was -N)

## 8. Frontend changes

### Industry detail page (`/industries/{gics_code}?iso2=XX`)

- Removed Rubric Score card (was showing +N/max with progress bar)
- Single Overall Score card remains
- Signals table: replaced Threshold and Signal columns with Score column (0-100 with color coding: green ≥60, yellow ≥40, red <40)

### Industry table (`/industries`)

- Removed Rubric column (was showing +/-N integer)

### Dashboard (`/dashboard`)

- Removed `rubric_score` from IndustryPreview interface

## 9. What does NOT change

- Rubric config file (`config/sector_macro_sensitivity_v1.json`) — sector definitions, indicator assignments, favorable_when directions, weights, rationales
- Evidence tracking — `point_ids`, `component_data` structure (just different signal fields)
- Company scoring pipeline — reads `IndustryScore.overall_score`, still 0-100
- Recommendation formula — 20% industry weight, Buy >70, Sell <40
- `absolute_score()` function — unchanged
- DB schema — `rubric_score` column remains (set equal to `overall_score`)

## 10. Acceptance criteria

- [x] `evaluate_rubric()` produces continuous 0-100 scores per indicator
- [x] Same indicator scored differently per sector based on `favorable_when` direction
- [x] Missing data scores 50.0 (neutral)
- [x] No rescaling step — `raw_score` directly becomes `overall_score`
- [x] Risk detection uses `score < 30` instead of `signal == -1`
- [x] Frontend displays per-indicator scores with color coding
- [x] Rubric column and card removed from UI
- [x] All tests pass (`pytest -q` — 167 tests)

## 11. Superseded sections in prior PRDs

| PRD | Section | Status |
|---|---|---|
| PRD 3.0 | §4.3 Signal evaluation | Superseded — binary +1/-1 replaced with continuous 0-100 |
| PRD 3.0 | §5.2 Pipeline | Superseded — percentile ranking and linear rescale removed |
| PRD 3.0 | §5.4 Risk detection | Superseded — `all_signals_negative` now uses `score < 30` |
| PRD 3.0 | §8 Packet example | Superseded — signal structure changed |
| PRD 3.0 | §11 Frontend pages | Superseded — rubric card and signal display replaced |
| PRD 5.0 | §6.4 "Industry scoring: linear rescale" | Superseded — replaced with continuous absolute scoring |
