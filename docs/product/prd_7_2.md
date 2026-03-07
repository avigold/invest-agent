# PRD 7.2 — FMP Data Preloader CLI

**Status**: In Progress
**Depends on**: PRD 7.1 (FMP Integration)

## Problem

With FMP integrated as the primary fundamentals source (PRD 7.1), data is fetched on-demand during `company_refresh` jobs — 3 API calls per company. There is no way to bulk-preload FMP data outside of user-triggered jobs. Cold starts after cache expiry are slow, and there's no cron-friendly mechanism to keep the cache warm.

Additionally, the `data_sync` handler was not updated with FMP-first routing during PRD 7.1.

## Solution

1. **New CLI command** `preload-fmp` that bulk-fetches FMP fundamentals for all companies in the database, with rate limiting and progress logging.
2. **Fix `data_sync` handler** to use FMP-first routing (matching `company_refresh`).
3. **Shared httpx client support** in `ingest_fmp_fundamentals_for_company` for connection pooling during bulk operations.

## Rate Limit Budget

| Metric | Value |
|---|---|
| FMP Ultimate limit | 3,000 req/min |
| Requests per company | 3 (income + balance + cashflow) |
| Theoretical max | ~1,000 companies/min |
| Safe target (50% headroom) | ~500 companies/min |
| Default concurrency | 3 parallel companies |

Freshness checks (720h / 30 days) skip already-cached companies with zero API calls.

## CLI Interface

```
python -m app.cli preload-fmp [OPTIONS]

Options:
  --concurrency INT   Max parallel companies (default: 3)
  --force             Re-fetch even if fresh
  --country TEXT      Filter by country ISO2 code (e.g., US, GB)
```

Output:
```
FMP Preload: 136 companies, concurrency=3
[  1/136] AAPL: 9 series, 41 years (0.9s)
[  2/136] MSFT: 9 series, 39 years (0.8s)
[  3/136] GOOGL: skipped (fresh)
...
Done: 100 fetched, 36 skipped (fresh), 0 failed in 2m 15s
```

## Files Changed

| File | Change |
|---|---|
| `app/cli.py` | Add `preload_fmp` command |
| `app/ingest/fmp_fundamentals.py` | Add optional `client` parameter |
| `app/jobs/handlers/data_sync.py` | FMP-first routing for company fundamentals |
| `tests/test_preload_fmp.py` | New tests |

## Acceptance Criteria

1. `python -m app.cli preload-fmp` processes all DB companies with FMP
2. `--country US` filters to US companies only
3. Re-running skips fresh companies (no wasted API calls)
4. `--force` bypasses freshness and re-fetches everything
5. FMP request rate stays well below 3,000/min
6. `data_sync` job uses FMP-first routing
7. All tests pass
