# PRD 6.1 — Screen Result Deep Analysis + Current Candidates

**Product**: investagent.app
**Status**: Complete
**Depends on**: PRD 6.0 (Historical Stock Screener)

## Problem

The screener result page shows statistical ranges of winner fundamentals (medians, means, min/max) but doesn't draw conclusions. Users want to understand *why* these companies produced extraordinary returns — not just what the numbers were — and identify companies in the database today that share the same ingredients.

## Solution

Two additions to the screener result, computed via a user-triggered job:

1. **AI Pattern Analysis**: Claude analyzes the full match data and identifies deeper patterns — sector concentration, fundamental archetypes, timing context, and caveats.

2. **Current Candidates**: Deterministic scoring of all DB companies against the "winner profile" (IQR of each fundamental metric across matches). Companies whose current fundamentals fall within the winner ranges score higher.

## Backend

### Analysis module (`app/analysis/screen_analysis.py`)

Prompt includes all match data, sector/country distributions, return stats, timing. Claude returns 5 sections: Pattern Summary, Fundamental Profile, Sector and Geography, Timing Patterns, Caveats.

Uses `claude-sonnet-4-6`, `temperature=0`, `max_tokens=3000`. Follows the same pattern as `app/analysis/recommendation_analysis.py`.

### Candidate matcher (`app/screen/candidate_matcher.py`)

- `compute_winner_profile(matches)` — P25/median/P75 for each fundamental metric across match `fundamentals_at_start`
- `score_candidates(db, winner_profile, winner_sectors)` — loads latest `CompanyScore.component_data["fundamental_ratios"]`, scores each company by how many metrics fall within the winner IQR + sector bonus. Returns top 20.

### Storage

New nullable `analysis` JSONB column on `screen_results`. Contains sections, current_candidates, winner_profile, model metadata.

### Job

New `screen_analysis` heavy job command. Params: `{screen_result_id}`. Free limit: 10/month.

## Frontend

- "Analyze Patterns" button on `/screener/:id` → submits job → polls → refetches
- Analysis sections rendered as cards when available
- Current Candidates table: ticker, name, match score, matching factors, current score
- Winner Profile reference table

## Files Changed

| File | Action |
|---|---|
| `docs/product/prd_6_1.md` | New |
| `app/db/models.py` | Modify — add `analysis` column |
| `alembic/versions/0009_add_screen_analysis.py` | New |
| `app/analysis/screen_analysis.py` | New |
| `app/screen/candidate_matcher.py` | New |
| `app/jobs/handlers/screen_analysis.py` | New |
| `app/jobs/handlers/__init__.py` | Modify |
| `app/jobs/schemas.py` | Modify |
| `app/api/routes_jobs.py` | Modify |
| `web/src/pages/ScreenerResult.tsx` | Modify |
| `tests/test_candidate_matcher.py` | New |

## Acceptance Criteria

1. Click "Analyze Patterns" on a screener result → job runs, analysis appears
2. Analysis sections provide deeper insight than raw statistics
3. Current Candidates table shows companies matching the winner profile
4. Excludes companies that were already in the matches (they already had their run)
5. `pytest -q` passes, `npm run build` clean
