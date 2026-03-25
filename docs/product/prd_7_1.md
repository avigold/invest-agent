# PRD 7.1 — FMP Fundamentals Integration

**Status**: Complete
## Problem

The prediction model (PRD 7.0) trains on ~1,600 observations spanning 20 years, but yfinance only provides ~4 years of fundamental data. This means ~60-80% of training observations lack fundamental features (ROE, net margin, debt/equity, FCF yield). LightGBM handles the NaNs but the model can't learn fundamental-based patterns from data it doesn't have.

Additionally, yfinance fundamentals are unreliable: inconsistent column names across exchanges, occasional empty DataFrames, no SLA, and the library breaks when Yahoo changes their internal API.

## Solution

Integrate Financial Modeling Prep (FMP) as the primary fundamentals data source, replacing yfinance fundamentals for both:

1. **Company scoring pipeline** — `company_refresh` job ingests fundamentals into CompanySeries/CompanySeriesPoint
2. **Prediction training pipeline** — `prediction_train` job attaches point-in-time fundamentals to Observation objects

FMP provides 13-41 years of standardized financial statements across 46+ global exchanges via a stable REST API. The user has purchased an FMP Ultimate plan.

## Impact

- Training observations with fundamentals: ~20% → ~90%+
- Historical depth: ~4 years → 13-41 years per company
- Data quality: unstable scraping → versioned REST API with SLA
- Field count: 15-35 per statement → 39-61 per statement

## FMP API

- Base URL: `https://financialmodelingprep.com/stable/`
- Auth: `?apikey=KEY` query parameter
- Endpoints:
  - `income-statement?symbol={TICKER}&limit=50` (39 fields)
  - `balance-sheet-statement?symbol={TICKER}&limit=50` (61 fields)
  - `cash-flow-statement?symbol={TICKER}&limit=50` (47 fields)
- Ticker format: identical to yfinance (`AAPL`, `AZN.L`, `SHOP.TO`, `SAP.DE`, etc.)
- Rate limit: 3,000 req/min on Ultimate plan

## Field Mapping

| Internal series_name | FMP field | FMP endpoint |
|---|---|---|
| `revenue` | `revenue` | income-statement |
| `net_income` | `netIncome` | income-statement |
| `operating_income` | `operatingIncome` | income-statement |
| `eps_diluted` | `epsDiluted` | income-statement |
| `total_assets` | `totalAssets` | balance-sheet-statement |
| `total_liabilities` | `totalLiabilities` | balance-sheet-statement |
| `stockholders_equity` | `totalStockholdersEquity` | balance-sheet-statement |
| `cash_from_ops` | `operatingCashFlow` | cash-flow-statement |
| `capex` | `capitalExpenditure` | cash-flow-statement |

Note: FMP capex is already positive (no `abs()` needed unlike yfinance).

## Data Model Changes

No schema changes. FMP data flows into existing `CompanySeries` and `CompanySeriesPoint` tables with `source="fmp"`. The `DataSource` table gets a new `"fmp"` row via `seed_sources.py`.

## Routing Logic

Current: US → SEC EDGAR, international → yfinance
New: ALL companies → FMP first, fallback to SEC EDGAR (US) or yfinance (international)

## Files Changed

| File | Action | Description |
|---|---|---|
| `docs/product/prd_7_1.md` | New | This PRD |
| `app/config.py` | Modify | Add `fmp_api_key: str` |
| `app/ingest/seed_sources.py` | Modify | Add FMP data source |
| `app/ingest/freshness.py` | Modify | Add `fmp_fundamentals: 720` |
| `app/ingest/fmp.py` | New | FMP HTTP client (3 fetch functions) |
| `app/ingest/fmp_fundamentals.py` | New | FMP ingestion for scoring pipeline |
| `app/jobs/handlers/company.py` | Modify | FMP-first routing with fallback |
| `app/score/company.py` | Modify | Add `"fmp"` to source filter |
| `app/screen/fundamentals_snapshot.py` | Modify | FMP path for training observations |
| `tests/test_fmp_fundamentals.py` | New | Unit tests |

## Acceptance Criteria

1. `pytest -q` passes (all existing + new tests)
2. `company_refresh` for AAPL logs "FMP fundamentals: AAPL" with 30+ annual values
3. `company_refresh` for international ticker uses FMP instead of yfinance
4. If FMP fails for a ticker, falls back to yfinance/EDGAR gracefully
5. Scoring still works (source filter includes "fmp")
6. `prediction_train` attaches fundamentals to >80% of observations
