# PRD 9.9 — Exclude Shell Companies from Deterministic Scoring

**Product**: investagent.app
**Version**: 9.9
**Date**: 2026-03-22
**Status**: Complete
**Priority**: MEDIUM

---

## Problem

2,291 companies (5% of the universe) have zero fundamental data — SPACs, blank-check companies, recently listed shells, and similar entities. The scoring system treats missing values as neutral (`absolute_score(None) → 50`), then `COMPANY_WEIGHTS_NO_FUNDAMENTALS` reweights to 100% market. Result: a shell company with good momentum scores 100 overall, competing alongside properly-evaluated businesses in recommendations.

9 of the top 100 overall scores have no fundamentals. This erodes trust in the platform's recommendations.

## Solution

Skip companies with zero fundamental data in `compute_company_scores()`. No score row → no recommendation → no pollution of rankings. When data arrives (next FMP sync + score sync), they get scored normally with no manual intervention.

## Changes

### `app/score/company.py`

In `compute_company_scores()`, after the `has_fundamentals` check (line 340), add:

```python
if not has_fundamentals:
    log_fn(f"  {t}: SKIPPED (no fundamental data)")
    continue
```

Log a summary count of skipped companies at the end.

### Downstream impact (no code changes needed)

- **`score_sync_handler`**: Already deletes old scores for all companies in the batch before adding new ones. Shell companies get their current-period scores deleted and no new score created. Previous-period scores are untouched (historical).
- **Recommendations**: Built from `CompanyScore` rows. No score → no recommendation.
- **Decision packets**: Built per score. No score → no packet.
- **Company list API**: Companies still appear but with `score: null`. Frontend handles this.
- **Individual stock page**: Already shows "N/A / No data" for missing fundamentals (PRD 9.8).
- **Auto-recovery**: When fundamental data arrives, the company will have `has_fundamentals = True` on the next scoring run and get scored normally.

### Cleanup

Run `score-sync --force` after deployment to remove existing scores for shell companies.

## Acceptance criteria

1. `compute_company_scores()` returns no `CompanyScore` for companies where `fundamentals.get(ticker)` is falsy
2. Log output shows count of skipped companies
3. After force rescore, companies without fundamentals have no `CompanyScore` at current `as_of`
4. `pytest -q` passes
