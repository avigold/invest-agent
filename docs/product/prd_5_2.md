# PRD 5.2 — Data Freshness & Smart Refresh

**Product**: investagent.app
**Version**: 5.2 (incremental, builds on PRD 5.1)
**Date**: 2026-03-01
**Status**: Complete
**Milestone**: 5

---

## 1. What this PRD covers

This document specifies the data freshness system that eliminates redundant API calls during refresh jobs. Before this change, every refresh re-fetched ALL historical data from ALL external sources regardless of staleness. A single `country_refresh` made ~160 API calls; most of that data is annual and hasn't changed since the last fetch.

## 2. Problem statement

### 2.1 Redundant fetching

| Source | Change frequency | Calls per country_refresh | Redundancy |
|---|---|---|---|
| World Bank | Annual | 70 (7 indicators x 10 countries) | ~99% within a month |
| IMF WEO | Annual | 10 | ~99% within a month |
| FRED | Daily/Monthly | 50 (5 series x 10 countries) | 45 calls redundant (same 5 series fetched 10x) |
| yfinance market | Daily | 10 | Minimal (changes daily) |
| GDELT | Monthly | 20 (3s rate limit each) | ~75% within a week |
| SEC EDGAR | Annual | ~50 (US companies) | ~99% within a month |
| yfinance fundamentals | Annual | ~100 (intl companies) | ~99% within a month |

### 2.2 FRED duplication

FRED series are global (not per-country), but were fetched once per country in the per-country loop — 5 series x 10 countries = 50 API calls for 5 unique datasets. The freshness check now deduplicates this naturally: the first country fetches FRED, subsequent countries find fresh artefacts and skip.

### 2.3 No staleness awareness

Users had no way to know whether a refresh was worth running. No API response indicated when scores were last computed.

## 3. Solution: per-entity freshness checking

### 3.1 Approach

Use the existing `artefacts` table (no schema changes) to check freshness before fetching. Each artefact already stores `data_source_id`, `fetch_params` (JSONB), and `fetched_at` (DateTime). A new `find_fresh()` method on `ArtefactStore` queries for a recent artefact matching the source and entity-specific parameters.

### 3.2 Staleness windows

New `FRESHNESS_HOURS` configuration in `app/ingest/freshness.py`:

| Source | Window | Rationale |
|---|---|---|
| `world_bank` | 720h (30 days) | Annual data |
| `imf_weo` | 720h (30 days) | Annual data |
| `fred` | 24h (1 day) | Daily/monthly series |
| `yfinance_market` | 4h | Market data changes intraday |
| `gdelt` | 168h (7 days) | Monthly aggregation |
| `sec_edgar` | 720h (30 days) | Annual filings |
| `yfinance_fundamentals` | 720h (30 days) | Annual filings |

### 3.3 Freshness check flow

```
For each source x entity:
  1. Query: SELECT * FROM artefacts
           WHERE data_source_id = :id
           AND fetch_params @> :filter
           AND fetched_at >= now() - :max_age
           ORDER BY fetched_at DESC LIMIT 1
  2. If found and not force → skip, return existing artefact ID
  3. If stale or force → fetch, store new artefact, proceed
```

The `fetch_params @>` (JSONB containment) operator matches on entity-identifying fields only (e.g., `{"iso2": "US", "indicator": "NY.GDP.MKTP.KD.ZG"}`), not date ranges. This means freshness is per-entity, not per-request.

### 3.4 Per-entity freshness

Freshness is tracked per-entity, not globally per-source. If you sync company A at 10:00 and company B at 14:00, company A's data is 4 hours older than B's. When the scheduler runs, it checks each entity's artefact individually — recently-synced entities are skipped, stale ones are re-fetched. This supports incremental expansion: adding 100 new companies and running `data_sync` fetches only those 100 (no fresh artefacts exist for them).

### 3.5 `force` parameter

All refresh and data_sync jobs accept `force: bool` in params. When `true`, freshness checks are bypassed and all data is re-fetched. Default is `false`.

## 4. `ArtefactStore.find_fresh()`

New async method on the existing `ArtefactStore` class:

```python
async def find_fresh(
    self,
    db: AsyncSession,
    data_source_id: uuid.UUID,
    fetch_params_filter: dict,
    max_age_hours: int,
) -> Artefact | None
```

Uses JSONB containment (`@>`) to match `fetch_params` against the filter, returns the most recent artefact if `fetched_at` is within `max_age_hours`. Returns `None` if no fresh artefact exists.

## 5. `data_sync` job command

New lightweight job that runs ingestion only (no scoring):

- Fetches all external data for all countries and all companies
- Respects freshness windows — only fetches stale data
- Registered in job command registry as `data_sync`
- Accepts `force: bool` parameter
- Designed for scheduler automation

## 6. `scored_at` in API responses

List endpoints (`GET /v1/countries`, `/v1/industries`, `/v1/companies`) now include `scored_at` — the timestamp when the decision packet was last built. Derived from `DecisionPacket.created_at`.

Users can see "Scores computed at 2026-03-01T07:12:00Z" and decide whether a refresh is worth running.

## 7. Daily scheduler

APScheduler running in-process with the FastAPI application:

| Time (UTC) | Job | Purpose |
|---|---|---|
| 06:00 | `data_sync` | Freshness-aware ingestion for all entities |
| 07:00 | `country_refresh` + `industry_refresh` + `company_refresh` | Rescore from stored data |

### 7.1 Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `SCHEDULER_ENABLED` | `false` | Enable/disable the scheduler |
| `SCHEDULER_TIMEZONE` | `UTC` | Timezone for cron expressions |

### 7.2 System user

Scheduler-created jobs are owned by a well-known system user (`00000000-0000-0000-0000-000000000001`, email `system@investagent.app`, role `admin`). This user is auto-created on scheduler startup if it doesn't exist.

## 8. FRED deduplication

FRED series are identical for all countries (global risk proxy). The freshness check naturally deduplicates: the first country's FRED fetch stores an artefact; subsequent countries find it fresh (within the 24h window) and skip. Over 10 countries, this reduces FRED API calls from 50 to 5 (one per series).

## 9. What does NOT change

- Artefact table schema (no migration needed)
- Series point upsert pattern (still idempotent)
- Scoring algorithms (absolute_score, weights, thresholds)
- Evidence chain (point_ids, artefact linkage)
- Multi-tenancy model (scores remain global)
- Decision packet structure
- Recommendation formula

## 10. Files changed

| File | Action |
|---|---|
| `app/ingest/freshness.py` | New — staleness windows config + `is_stale()` helper |
| `app/ingest/artefact_store.py` | Modified — added `find_fresh()` method |
| `app/ingest/world_bank.py` | Modified — freshness check + `force` param |
| `app/ingest/imf.py` | Modified — freshness check + `force` param |
| `app/ingest/fred.py` | Modified — freshness check + `force` param |
| `app/ingest/gdelt.py` | Modified — freshness check + `force` param |
| `app/ingest/marketdata.py` | Modified — freshness check + `force` param |
| `app/ingest/sec_edgar.py` | Modified — freshness check + `force` param |
| `app/ingest/yfinance_fundamentals.py` | Modified — freshness check + `force` param |
| `app/ingest/company_marketdata.py` | Modified — freshness check + `force` param |
| `app/jobs/handlers/country.py` | Modified — reads `force` from params, passes to ingest |
| `app/jobs/handlers/company.py` | Modified — reads `force` from params, passes to ingest |
| `app/jobs/handlers/data_sync.py` | New — ingestion-only handler |
| `app/jobs/handlers/__init__.py` | Modified — registered `data_sync` |
| `app/jobs/schemas.py` | Modified — added `DATA_SYNC` enum |
| `app/jobs/queue.py` | Modified — added `data_sync` to `HEAVY_COMMANDS` |
| `app/api/routes_jobs.py` | Modified — added `data_sync` to free limits |
| `app/api/routes_countries.py` | Modified — added `scored_at` to response |
| `app/api/routes_industries.py` | Modified — added `scored_at` to response |
| `app/api/routes_companies.py` | Modified — added `scored_at` to response |
| `app/scheduler/daily.py` | New — APScheduler implementation |
| `app/scheduler/__init__.py` | New — package init |
| `app/config.py` | Modified — added `scheduler_enabled`, `scheduler_timezone` |
| `app/main.py` | Modified — scheduler lifecycle in lifespan |
| `pyproject.toml` | Modified — added `apscheduler` dependency |
| `tests/test_freshness.py` | New — freshness system tests |
| `tests/test_ingest.py` | Modified — mocked `find_fresh` in GDELT tests |

## 11. Acceptance criteria

- [x] `ArtefactStore.find_fresh()` returns fresh artefact or None
- [x] All ingest functions check freshness before fetching
- [x] `force=True` bypasses freshness checks
- [x] FRED deduplicated across countries via freshness check
- [x] `data_sync` job command runs ingestion without scoring
- [x] `scored_at` included in list API responses
- [x] APScheduler configured with cron jobs at 06:00 and 07:00 UTC
- [x] Scheduler gated by `SCHEDULER_ENABLED` env var
- [x] All tests pass (175 tests)

## 12. Superseded sections in prior PRDs

None — this is additive functionality. Prior PRDs described ingestion without freshness awareness; this PRD adds the freshness layer on top.
