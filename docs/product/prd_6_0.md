# PRD 6.0 — Historical Stock Screener

**Product**: investagent.app
**Status**: In Progress

## Problem

Users want to answer research questions like: "Which companies gained 300%+ over any 5-year window in recent history, and what did they look like before the run?" This requires scanning extended price histories, identifying exceptional return windows, and analyzing the common characteristics of winners at the start of their runs.

## Solution

A Historical Stock Screener that:
1. Pulls 15-20 years of daily price history from yfinance for the DB universe
2. Scans rolling N-year windows to find stocks exceeding a return threshold
3. Snapshots fundamentals at the start of each winning window
4. Computes a common features analysis across all matches
5. Stores results for viewing in the frontend

## Data Sources

- **Price history**: yfinance `download()` — provides 20+ years of daily OHLC for most US and international equities
- **Fundamentals**: yfinance `Ticker.income_stmt`, `balance_sheet`, `cashflow` — typically 4-10 years of annual data
- **Universe**: Companies already in the DB (~136 across 10 countries)

### Known Limitation: Survivorship Bias

Only companies currently in the database are screened. Delisted companies that may have had significant runs before delisting are not captured. This is acceptable for v1.

## Backend

### Screening Engine (`app/screen/`)

**`price_history.py`** — Fetch extended daily close prices via `yf.download()` in batches of 50 tickers. Returns `{ticker: pd.Series}`.

**`return_scanner.py`** — For each ticker, resample daily prices to month-end, compute rolling N-year returns, find windows exceeding the threshold. Keep only the best (highest return) non-overlapping window per ticker. Returns `list[ReturnMatch]` sorted by return descending.

**`fundamentals_snapshot.py`** — For each matched ticker, fetch yfinance financial statements and extract key ratios (ROE, net margin, debt/equity, FCF, asset turnover) from the fiscal year closest to the window start date.

**`common_features.py`** — Statistical summary: sector distribution, country distribution, return stats (median/mean/min/max), window start year histogram, fundamental stats per metric (count/median/mean/range/stdev).

### DB Model

New `screen_results` table:
- `id` UUID PK, `user_id` FK → users (CASCADE), `job_id` FK → jobs (SET NULL)
- `screen_name` varchar(200), `screen_version` varchar(50) default `"screen_v1"`
- `params` JSONB — `{return_threshold, window_years, lookback_years, include_fundamentals}`
- `summary` JSONB — `{total_screened, matches_found, common_features}`
- `matches` JSONB — `[{ticker, name, country, gics, window_start, window_end, return_pct, start_price, end_price, fundamentals_at_start}]`
- `artefact_ids` JSONB, `created_at` timestamptz
- Indexes on `user_id`, `created_at`

### Job

New `stock_screen` heavy job command. Default params: `return_threshold=3.0` (300%), `window_years=5`, `lookback_years=20`, `include_fundamentals=true`. Free tier limit: 5/month.

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/screener/results` | List user's screen results (last 50) |
| `GET` | `/v1/screener/results/{id}` | Full result with matches + features |
| `DELETE` | `/v1/screener/results/{id}` | Delete a result |

Screening is initiated by submitting a `stock_screen` job via `POST /api/jobs`.

## Frontend

### Screener Page (`/screener`)
- Configuration form: return threshold (%), window years, lookback years, include fundamentals toggle
- "Run Screen" button → submits job → redirects to job detail for live logs
- Past results table: name, matches, screened, date, link to detail

### Screener Result Page (`/screener/:id`)
- Header: screen name, parameters, match count
- Common Features: sector distribution, country distribution, fundamental stats table
- Matches table: ticker, name, return %, period, start/end price, key fundamentals

## Files Changed

| File | Action |
|---|---|
| `docs/product/prd_6_0.md` | New — this PRD |
| `app/db/models.py` | Modify — add ScreenResult |
| `alembic/versions/0008_add_screen_results.py` | New — migration |
| `app/screen/__init__.py` | New |
| `app/screen/price_history.py` | New |
| `app/screen/return_scanner.py` | New |
| `app/screen/fundamentals_snapshot.py` | New |
| `app/screen/common_features.py` | New |
| `app/jobs/handlers/stock_screen.py` | New |
| `app/jobs/handlers/__init__.py` | Modify — register |
| `app/jobs/schemas.py` | Modify — add STOCK_SCREEN |
| `app/api/routes_jobs.py` | Modify — add _FREE_LIMITS |
| `app/api/routes_screener.py` | New |
| `app/main.py` | Modify — register router |
| `web/src/pages/Screener.tsx` | New |
| `web/src/pages/ScreenerResult.tsx` | New |
| `web/src/App.tsx` | Modify — add routes |
| `web/src/components/NavBar.tsx` | Modify — add link |
| `tests/test_screener.py` | New |

## Acceptance Criteria

1. Submit `stock_screen` job with `{return_threshold: 3.0, window_years: 5}` — job completes
2. Result shows matched tickers with return %, window dates, fundamentals at start
3. Common features analysis shows sector/country distributions and fundamental stats
4. `/v1/screener/results` lists the user's results; other users cannot access them
5. Frontend screener page renders form, submits jobs, displays results
6. `pytest -q` passes, `npm run build` clean
