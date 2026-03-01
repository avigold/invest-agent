# PRD 5.4 — Fix Recommendation Distribution (Remove Industry Double-Counting + Populate GICS Codes)

**Product**: investagent.app
**Version**: 5.4 (incremental, builds on PRD 5.3)
**Date**: 2026-03-01
**Status**: Complete
**Milestone**: 5

---

## 1. What this PRD covers

This document specifies changes to fix the recommendation distribution, which currently produces 408 Hold, 3 Buy, and 0 Sell recommendations — rendering the system effectively useless for actionable decisions.

## 2. Problem statement

### 2.1 Industry double-counting

The company score formula includes `industry_context` at 20% weight:

```
company_score = 0.50 * fundamental + 0.30 * market + 0.20 * industry_context
```

The recommendation composite then includes industry again at 20%:

```
composite = 0.20 * country + 0.20 * industry + 0.60 * company
```

Industry effectively has 32% total influence (12% via company + 20% direct), while fundamentals — the layer with the widest score range — only has 30%. This compresses the composite toward the center (Hold).

### 2.2 Missing GICS codes

~270 user-added companies were inserted with `gics_code=""`. Both the `industry_context` company sub-score and the recommendation industry score default to 50.0 (neutral) when GICS is missing. This further compresses scores toward Hold.

## 3. Solution

### 3.1 Remove industry context from company score

New company score formula:

```
company_score = 0.60 * fundamental + 0.40 * market
```

When no fundamental data is available:

```
company_score = 0.0 * fundamental + 1.0 * market
```

The recommendation composite formula is **unchanged**:

```
composite = 0.20 * country + 0.20 * industry + 0.60 * company
```

**Effective weights in composite after fix**: 36% fundamental, 24% market, 20% country, 20% industry. No double-counting.

### 3.2 Populate missing GICS codes

Both `company_refresh` and `add_companies_by_market_cap` handlers will backfill missing GICS codes using `enrich_with_yfinance_async()` + `map_sector_to_gics()` from `app/ingest/company_lookup.py`.

- On `company_refresh`: after building the company list, enrich any company with `gics_code=""`.
- On `add_companies_by_market_cap`: backfill existing companies with `gics_code=""` at job start, and enrich newly added companies before ingest.

### 3.3 Version bumps

| Constant | Old | New |
|---|---|---|
| `COMPANY_CALC_VERSION` | `company_v2` | `company_v3` |
| `COMPANY_SUMMARY_VERSION` | `company_summary_v2` | `company_summary_v3` |
| `RECOMMENDATION_VERSION` | `recommendation_v1` | `recommendation_v2` |

### 3.4 Global ranking in add_companies_by_market_cap

The `build_company_packet` function computes rank from the `all_scores` list it receives. The `add_companies_by_market_cap` handler now loads **all** `CompanyScore` rows for the current `as_of` + `calc_version` from the DB before building packets, so ranks reflect the global position across all scored companies — not just the batch.

### 3.5 No migration needed

The `industry_context_score` column remains in the `CompanyScore` model; new scores set it to 0. Old scores are replaced on re-computation.

## 4. Files changed

| File | Action |
|---|---|
| `app/score/versions.py` | Modify — version bumps, new weights |
| `app/score/company.py` | Modify — remove industry context from scoring |
| `app/jobs/handlers/add_companies.py` | Modify — GICS enrichment (backfill + new), global ranking fix |
| `app/jobs/handlers/company.py` | Modify — GICS backfill on refresh |
| `web/src/pages/CompanyDetail.tsx` | Modify — remove industry context card |
| `tests/test_company_search.py` | Modify — add version/weight tests |

## 5. Acceptance criteria

- [x] `COMPANY_WEIGHTS` has keys `fundamental` and `market` only (no `industry_context`)
- [x] `COMPANY_WEIGHTS` values sum to 1.0
- [x] Company score formula uses only fundamental and market sub-scores
- [x] `industry_context_score` set to 0 in new CompanyScore records
- [x] GICS codes are backfilled for existing companies with `gics_code=""` during both handlers
- [x] Version constants bumped correctly
- [x] Frontend shows 3 score cards: Overall, Fundamental (60%), Market (40%)
- [x] All tests pass (190 tests)
- [x] `add_companies_by_market_cap` ranks against all scored companies, not just the batch
- [ ] After `company_refresh`, recommendation distribution shows meaningful Buy/Hold/Sell spread

## 6. What does NOT change

- Recommendation composite formula and weights (`0.20 country + 0.20 industry + 0.60 company`)
- Recommendation thresholds (buy: 70, sell: 40)
- Country and industry scoring
- Evidence chain and artefact lineage
- Database schema
