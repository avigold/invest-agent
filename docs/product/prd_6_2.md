# PRD 6.2 — Screener v2: Fixed Forward Returns + Contrast Analysis

**Status**: In Progress
**Date**: 2026-03-05
**Depends on**: PRD 6.0 (Stock Screener), PRD 6.1 (Screen Analysis)

## Problem

The v1 screener has three methodological flaws that limit its usefulness:

1. **Cherry-picked labels**: Selecting the single best N-year window per stock biases toward peak returns and creates overlapping-window leakage. This is not a fair basis for analyzing pre-conditions.
2. **No contrast with non-winners**: Computing statistics on winners alone cannot reveal what's actually distinctive — if 80% of all stocks share a trait, it's not a useful signal even if 100% of winners have it.
3. **Sparse scoring overlap**: Only 3 metrics (ROE, net margin, debt/equity) overlap between the screener snapshot and current company data, so candidate matching lacks discrimination.

## Solution

Replace the scanner with fixed forward returns at annual observation points, add price-derived trailing features (available for the full 20-year history), and contrast winners against non-winners to find what's actually distinctive.

**v1**: "Find the best 5-year window per stock where returns exceeded 300%"
**v2**: "For every stock at every year, what happened over the next 5 years? What distinguished the 300%+ achievers from those that didn't?"

## Key Concepts

### Observation
A (company, date) pair with a forward outcome and trailing pre-conditions. ~136 tickers x ~15 annual dates = ~2,000 observations per screen run.

### Contrast Analysis
Compare winner observations vs non-winner observations for each feature. Compute lift (how much more winners had) and separation (Mann-Whitney AUC, how cleanly the feature divides the groups). Features with high separation are weighted more heavily in candidate scoring.

### Catastrophe Profiling
Same contrast approach, splitting on "catastrophe" (>80% forward drawdown) instead of "winner." Identifies what predicts disaster, used as a penalty in candidate scoring.

## Files Changed

| File | Action |
|---|---|
| `app/screen/forward_scanner.py` | New — observation generation + trailing features |
| `app/screen/contrast.py` | New — winner vs non-winner contrast + catastrophe profiling |
| `app/screen/candidate_scorer.py` | New — v2 discrimination-weighted candidate scoring |
| `tests/test_forward_scanner.py` | New |
| `tests/test_contrast.py` | New |
| `app/screen/fundamentals_snapshot.py` | Modify — add fetch_fundamentals_for_observations() |
| `app/jobs/handlers/stock_screen.py` | Modify — add v2 flow |
| `app/jobs/handlers/screen_analysis.py` | Modify — v2 scorer + prompt |
| `app/analysis/screen_analysis.py` | Modify — v2 prompt template |
| `app/api/routes_screener.py` | Modify — add screen_version to list |
| `web/src/pages/Screener.tsx` | Modify — default to v2 |
| `web/src/pages/ScreenerResult.tsx` | Modify — v2 layout |

## Acceptance Criteria

1. v2 screen generates fixed-forward observations at annual intervals
2. Contrast table shows lift and separation for each feature
3. Catastrophe events are identified and profiled
4. Candidate scoring uses discrimination-weighted features with catastrophe penalty
5. AI analysis receives contrast data and produces 6 sections
6. Existing v1 results remain viewable
7. All tests pass, frontend builds clean
