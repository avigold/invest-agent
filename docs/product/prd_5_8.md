# PRD 5.8 — Custom Scoring Profiles

**Status**: Complete
**Depends on**: PRD 5.0 (recommendations), PRD 5.7 (recommendation detail)

## Overview

Power users can create custom scoring profiles that adjust the weights used to compute recommendation composite scores. Profiles are per-user and affect only the recommendations list view — no new DB score rows are created, and other users are unaffected.

## User Stories

1. As a user, I can open an advanced settings modal from the recommendations list view.
2. As a user, I can adjust recommendation-level weights (country/industry/company balance) and buy/sell thresholds.
3. As a user, I can adjust country sub-score weights (macro/market/stability) and individual indicator weights.
4. As a user, I can adjust company sub-score weights (fundamental/market) and individual ratio/metric weights.
5. As a user, I can save my weight configuration as a named profile.
6. As a user, I can see at a glance which profile is active (default vs custom).
7. As a user, I can switch between saved profiles and system defaults.
8. As a user, my recommendations are rescored and reordered according to my active profile.

## Tunable Parameters

### Recommendation Level
- `country` weight (default: 0.20)
- `industry` weight (default: 0.20)
- `company` weight (default: 0.60)
- Buy threshold (default: 70)
- Sell threshold (default: 40)

### Country Sub-Scores
- `macro` weight (default: 0.50)
- `market` weight (default: 0.40)
- `stability` weight (default: 0.10)

### Country Macro Indicators (10, equal weight by default)
gdp_growth, inflation, unemployment, govt_debt_gdp, current_account_gdp, fdi_gdp, reserves, gdp_per_capita, market_cap_gdp, household_consumption_pc

### Country Market Metrics (3, equal weight by default)
return_1y, max_drawdown, ma_spread

### Company Sub-Scores
- `fundamental` weight (default: 0.60)
- `market` weight (default: 0.40)

### Company Fundamental Ratios (6, equal weight by default)
roe, net_margin, debt_equity, revenue_growth, eps_growth, fcf_yield

### Company Market Metrics (3, equal weight by default)
return_1y, max_drawdown, ma_spread

### Not Tunable
- Industry score internals (rubric-based, not decomposable into numeric indicators)
- Absolute scoring thresholds (floor, ceiling, direction) — these are data-model constants
- Which indicators exist — fixed by data source contracts

## Technical Approach

### Rescoring Strategy
All raw indicator values are stored in `component_data` JSONB on `CountryScore` and `CompanyScore`. Rescoring re-applies `absolute_score()` with user-defined weights to these stored values — no need to re-run the data pipeline. Rescoring is ephemeral (computed on-the-fly per API request).

### Database
New `scoring_profiles` table with JSONB `config` column validated by Pydantic.

### API
- CRUD endpoints for profiles at `/v1/scoring-profiles`
- Modified `GET /v1/recommendations` accepts optional `profile_id` query param
- Response includes `profile_id`, `profile_name`, `is_custom_profile` metadata

### Frontend
- Profile selector badge next to recommendations page title
- Modal with collapsible sections for each scoring layer
- Weight sliders with auto-normalization for constrained groups

## Acceptance Criteria

1. User can create, update, delete, and switch scoring profiles.
2. Activating a profile rescores and reorders the recommendations list.
3. Deactivating returns to system defaults.
4. Other users are not affected by any profile.
5. Profiles with no fundamental ratio weights set (all zero) are rejected.
6. Group weights (country/industry/company) always sum to 1.0.
7. Buy threshold must be greater than sell threshold.
8. All existing tests continue to pass.
