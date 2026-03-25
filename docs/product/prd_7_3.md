# PRD 7.3 — Scheduled Data Refresh Strategy

**Status**: Complete
**Depends on**: PRD 7.1 (FMP Integration), PRD 7.2 (FMP Preloader CLI)

## Problem

With 45,698 companies across 69 exchanges in the database, the existing scheduler is inadequate:

- `data_sync` only covers ~136 config-file companies, not the full 45k universe
- The monolithic `company_refresh` handler tries to do ingestion + scoring + packets in one pass — unworkable at 45k scale
- No dedicated stock price sync (yfinance, 4h freshness)
- No automated new company discovery

## Solution

Decompose refresh into **5 granular job handlers**, each aligned to the natural update cadence of its data source. The existing freshness system (`FRESHNESS_HOURS`) ensures zero wasted API calls — running a job more often than its freshness window costs nothing.

## Schedule (all times UTC)

| Cron | Job | Scope | Est. Duration |
|---|---|---|---|
| `0 0,4,8,12,16,20 * * *` | `price_sync` | Stock prices: ~45k companies + 10 country indices | ~20-30 min |
| `0 6 * * *` | `macro_sync` (scope=daily) | FRED 5 series + country index prices | < 1 min |
| `0 4 * * 0` | `fmp_sync` | FMP fundamentals for all ~45k companies | 5-90 min |
| `0 6 * * 0` | `score_sync` | Re-score companies with stale scores | ~15-20 min |
| `0 3 1 * *` | `macro_sync` (scope=monthly) | World Bank + IMF + GDELT for 10 countries | ~5 min |
| `0 7 1 * *` | full rescore | country_refresh + industry_refresh | ~2 min |
| `0 2 1 * *` | `discover_companies` | FMP screener: newly listed companies | ~2 min |

**Rate limit budget**: FMP = 3,000 req/min. `fmp_sync` at concurrency=10 → ~1,800 req/min (60%). `price_sync` uses yfinance (no shared API key). Jobs are time-staggered.

## Data Source Cadence Rationale

| Data Source | Actually Changes | Freshness Window | Schedule |
|---|---|---|---|
| Stock prices (yfinance) | Every trading day | 4 hours | Every 4 hours |
| FRED macro (rates, spreads) | Daily/monthly | 24 hours | Daily |
| GDELT stability | Monthly aggregation | 7 days | Monthly |
| FMP fundamentals | Quarterly (earnings) | 30 days | Weekly |
| World Bank, IMF | Annually (Q1-Q2) | 30 days | Monthly |
| New listings | IPOs | N/A | Monthly |

## New Job Handlers

### `fmp_sync` — FMP fundamentals for all DB companies
- Reuses proven logic from `_preload_fmp_async` (PRD 7.2)
- Shared `httpx.AsyncClient`, `asyncio.Semaphore(concurrency)`
- Freshness-aware: 99% skipped outside earnings season

### `price_sync` — Stock prices for all companies + indices
- `ingest_market_data_for_company` per company
- `ingest_market_data_for_country` for 10 investable countries
- 4h freshness, semaphore concurrency

### `score_sync` — Score companies with stale/missing scores
- Checks `CompanyScore` for current `as_of`; scores only stale companies
- `compute_company_scores` + `detect_company_risks` + `build_company_packet`

### `macro_sync` — Country-level macro data
- Scope param: `daily` (FRED + market only) or `monthly` (all: WB, IMF, FRED, GDELT, market)
- 10 countries from config, sequential

### `discover_companies` — New company discovery
- Iterates FMP screener per-exchange (bypasses 5,000 single-call cap)
- Deduplicates against existing tickers

## CLI Commands

All handlers also available as CLI commands for cron use:

```
python -m app.cli sync-prices [--concurrency 5] [--country US]
python -m app.cli sync-macro [--scope daily|monthly|all] [--force]
python -m app.cli score-all [--force] [--country US]
python -m app.cli discover-companies [--min-market-cap 100000000]
python -m app.cli preload-fmp [--concurrency 10] [--force]  # existing
```

## Files Changed

| File | Action |
|---|---|
| `docs/product/prd_7_3.md` | New — this PRD |
| `app/jobs/handlers/fmp_sync.py` | New |
| `app/jobs/handlers/price_sync.py` | New |
| `app/jobs/handlers/score_sync.py` | New |
| `app/jobs/handlers/macro_sync.py` | New |
| `app/jobs/handlers/discover_companies.py` | New |
| `app/jobs/handlers/__init__.py` | Modify — register 5 handlers |
| `app/jobs/queue.py` | Modify — HEAVY_COMMANDS |
| `app/scheduler/daily.py` | Modify — 7 cron jobs |
| `app/cli.py` | Modify — 4 new CLI commands |
| `tests/test_fmp_sync.py` | New |
| `tests/test_price_sync.py` | New |
| `tests/test_score_sync.py` | New |
| `tests/test_scheduler_schedule.py` | New |

## Acceptance Criteria

1. All 5 new handlers registered and callable via job system
2. Scheduler registers 7 cron jobs when `SCHEDULER_ENABLED=true`
3. CLI commands work for cron: `sync-prices`, `sync-macro`, `score-all`, `discover-companies`
4. `fmp_sync` processes all ~45k companies, skipping fresh ones
5. `price_sync` handles companies + country indices
6. `score_sync` only scores companies with stale/missing scores
7. FMP rate usage stays under 3,000 req/min
8. All tests pass
