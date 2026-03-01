# PRD 5.3 — Add Companies (Search + Bulk by Market Cap)

**Product**: investagent.app
**Version**: 5.3 (incremental, builds on PRD 5.0)
**Date**: 2026-03-01
**Status**: Complete
**Milestone**: 5

---

## 1. What this PRD covers

This document specifies the "Add Companies" feature — a way for users to expand the company universe beyond the pre-configured ~148 companies. Users can search by name/ticker or bulk-add the next N companies by market cap. Added companies are immediately ingested, scored, and visible on the Companies page.

## 2. Problem statement

### 2.1 Fixed company universe

The company universe is defined in `config/company_universe_v2.json`. Users cannot add companies of interest that aren't in this list. The config file is the only entry point for the company module.

### 2.2 No discovery mechanism

Users have no way to search for or discover companies. They must know the exact ticker and manually edit the config file (developer workflow, not user workflow).

### 2.3 Expansion requires re-scoring everything

The `company_refresh` job processes all companies in config. Adding 10 new companies means re-ingesting and re-scoring 148 existing ones too. Since scores are absolute (not relative), this is wasteful.

## 3. Solution

### 3.1 DB as source of truth

The database becomes the authoritative source for which companies to process. The JSON config remains as a seed (upserted on each `company_refresh`), but companies can also exist only in the DB with `config_version="user_added"`. The `company_refresh` handler queries for DB-only companies after the config upsert loop and includes them in processing.

### 3.2 Company search (SEC + yfinance)

- **US companies**: SEC's `company_tickers.json` (~13K public companies with CIK, ticker, name). Cached in-memory with 24h TTL via `SECTickerCache`.
- **International/any ticker**: `GET /v1/companies/enrich?ticker=7203.T` fetches metadata via `yf.Ticker(symbol).info`.
- Search results include an `already_added` flag by checking the DB.

### 3.3 Bulk add by market cap (yfinance screener)

The `add_companies_by_market_cap` job command uses the **yfinance screener API** (`yf.screen()`) to fetch US equities pre-sorted by market cap descending. The screener returns 250 results per page with market cap included — no per-ticker lookups needed.

Flow:
1. Fetch screener pages until `count` new companies are found (skipping those already in DB)
2. Cross-reference SEC ticker cache for CIK
3. Skip tickers whose CIK already exists in DB (duplicate share classes, e.g. GOOG vs GOOGL)
4. Insert into Company table with `config_version="user_added"`
5. Run ingest (EDGAR/yfinance fundamentals + market data) for new companies only
6. Score, detect risks, build decision packets for new companies only

This is a single end-to-end job — companies appear on the Companies page with scores when the job completes.

### 3.4 GICS sector mapping

yfinance returns free-text sector names. A static lookup maps them to 2-digit GICS codes:

| yfinance sector | GICS code |
|---|---|
| Technology / Information Technology | 45 |
| Financial Services / Financials | 40 |
| Healthcare / Health Care | 35 |
| Energy | 10 |
| Industrials | 20 |
| Consumer Cyclical / Consumer Discretionary | 25 |
| Consumer Defensive / Consumer Staples | 30 |
| Communication Services | 50 |
| Utilities | 55 |
| Real Estate | 60 |
| Basic Materials / Materials | 15 |

### 3.5 Duplicate CIK handling

Some companies have multiple share classes with the same CIK (e.g. GOOGL and GOOG both have CIK `0001652044`). The `companies` table has a partial unique index `uq_companies_cik_not_null` on CIK where CIK is not null.

Resolution: when adding a company whose CIK already exists in the DB, the company is **skipped** (not added with null CIK). The existing share class is sufficient for scoring purposes.

## 4. API endpoints

### 4.1 Search

`GET /v1/companies/search?q=apple`

Returns `list[SearchResult]`:
```json
[
  {
    "ticker": "AAPL",
    "name": "Apple Inc",
    "cik": "0000320193",
    "country_iso2": "US",
    "gics_code": "",
    "market_cap": null,
    "already_added": true
  }
]
```

Searches SEC ticker cache: exact ticker match first, then ticker prefix, then name substring. Limited to 20 results.

### 4.2 Enrich

`GET /v1/companies/enrich?ticker=7203.T`

Returns `SearchResult` with yfinance metadata (market cap, sector → GICS code, country → ISO2). For US tickers, also includes CIK from SEC cache.

### 4.3 Add

`POST /v1/companies/add`

Request:
```json
{
  "companies": [
    {"ticker": "NEWCO", "name": "New Company", "cik": null, "country_iso2": "US", "gics_code": "45"}
  ]
}
```

Response:
```json
{"added": 1, "skipped": 0, "tickers_added": ["NEWCO"], "tickers_skipped": []}
```

Skips tickers already in DB and tickers whose CIK already exists.

### 4.4 Bulk add job

Job command: `add_companies_by_market_cap`
Params: `{"count": 100}`
Heavy command (uses concurrency semaphore).
Free plan limit: 3/month.

## 5. company_refresh handler change

After the config upsert loop, the handler loads DB-only companies:

```python
config_tickers = {cc["ticker"] for cc in companies_config}
if not ticker_filter:
    # Load all companies not in config
    result = await db.execute(
        select(Company).where(Company.ticker.notin_(config_tickers))
    )
    companies.extend(result.scalars().all())
elif ticker_filter not in config_tickers:
    # Single ticker not in config — look up in DB
    result = await db.execute(
        select(Company).where(Company.ticker == ticker_filter)
    )
    extra = result.scalar_one_or_none()
    if extra:
        companies.append(extra)
```

## 6. Frontend

### 6.1 Companies page

"+ Add Companies" button added next to "Refresh Companies", linking to `/companies/add`.

### 6.2 Add Companies page (`/companies/add`)

Two tabs:

**Search tab:**
- Text input with 300ms debounce → `GET /v1/companies/search?q=...`
- Results table with checkboxes (already-added companies grayed with badge)
- "Add Selected" button → `POST /v1/companies/add`
- Success banner with "Refresh Companies Now" button

**Bulk Add tab:**
- Number input (1–500, default 100)
- "Add Next N by Market Cap" button → enqueues `add_companies_by_market_cap` job
- Navigates to job detail page

## 7. Files changed

| File | Action |
|---|---|
| `app/ingest/company_lookup.py` | New — SEC ticker cache, yfinance enrichment, GICS/country mapping |
| `app/api/routes_company_search.py` | New — search, enrich, add endpoints |
| `app/jobs/handlers/add_companies.py` | New — bulk add handler (screener + ingest + score) |
| `app/jobs/handlers/__init__.py` | Modified — register handler |
| `app/jobs/schemas.py` | Modified — add enum value |
| `app/jobs/queue.py` | Modified — add to HEAVY_COMMANDS |
| `app/api/routes_jobs.py` | Modified — add to free limits |
| `app/main.py` | Modified — register router |
| `app/jobs/handlers/company.py` | Modified — process DB-only companies |
| `web/src/App.tsx` | Modified — add route |
| `web/src/pages/Companies.tsx` | Modified — add button |
| `web/src/pages/AddCompanies.tsx` | New — search + bulk-add page |
| `tests/test_company_search.py` | New — 11 tests |

No DB migration needed — `Company` model already has all required fields including `config_version`.

## 8. Acceptance criteria

- [x] SEC ticker cache loads and searches ~13K companies
- [x] Search endpoint returns results with `already_added` flag
- [x] Enrich endpoint returns yfinance metadata with GICS mapping
- [x] Add endpoint inserts companies, skips duplicates (ticker and CIK)
- [x] `add_companies_by_market_cap` uses yfinance screener (not per-ticker lookups)
- [x] Bulk add job runs ingest + scoring for new companies (no full re-score)
- [x] Duplicate share classes (same CIK) are skipped
- [x] `company_refresh` includes DB-only companies
- [x] Frontend search with debounce, selection, and add flow
- [x] Frontend bulk add enqueues job and navigates to job detail
- [x] All tests pass (186 tests)

## 9. What does NOT change

- Company scoring algorithms (absolute_score, weights, thresholds)
- Decision packet structure
- Artefact/evidence chain
- Config file format (still used as seed)
- Existing company data or scores
