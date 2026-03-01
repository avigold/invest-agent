# PRD 4.0 — Company Module v1 (US-First)

**Product**: investagent.app
**Version**: 4.0 (incremental, builds on PRD 3.0)
**Date**: 2026-03-01
**Status**: Complete
**Milestone**: 4

---

## 1. What this PRD covers

This document specifies the Company Module — the first company-level research pipeline in Invest Agent. It describes the SEC EDGAR data ingestion, market data pipeline, hybrid scoring methodology (fundamental + market + industry context), risk detection, decision packets with full evidence lineage, API endpoints, and frontend pages added in Milestone 4.

For the foundation, see [PRD 1.0](prd_1_0.md). For country data, see [PRD 2.0](prd_2_0.md). For industry scoring, see [PRD 3.0](prd_3_0.md).

## 2. Decisions made since PRD 3.0

| Decision | Detail |
|----------|--------|
| Company universe scope | **25 US companies spanning all 11 GICS sectors** — not user-configurable for MVP. Companies are defined in `config/company_universe_v1.json`. |
| Filing data source | **SEC EDGAR Company Facts API** (XBRL) — free, no auth required, 10 req/sec rate limit. User-Agent header required. |
| Market data source | **yfinance** — reuses existing `fetch_index_history` from M2, applied to individual stock tickers. |
| Scoring weights | **Fundamental 50%, Market 30%, Industry Context 20%** — fundamentals are primary for company evaluation. |
| Industry context input | **IndustryScore from M3** — company's GICS sector score for US, defaults to 50.0 if unavailable. |

## 3. Company universe

25 US public companies configured in `config/company_universe_v1.json`, spanning all 11 GICS sectors:

| Sector (GICS) | Companies |
|----------------|-----------|
| Energy (10) | XOM, CVX |
| Materials (15) | (included in universe) |
| Industrials (20) | HD |
| Consumer Disc. (25) | AMZN, TSLA, COST |
| Consumer Staples (30) | PG, KO, PEP |
| Health Care (35) | JNJ, UNH, LLY, MRK, ABBV |
| Financials (40) | JPM, V, BRK-B |
| Info Tech (45) | AAPL, MSFT, NVDA, CRM |
| Comm. Services (50) | GOOGL, META |
| Utilities (55) | NEE |
| Real Estate (60) | AMT |

Each entry includes: ticker, CIK (10-digit zero-padded), name, gics_code, country_iso2.

## 4. Data sources

### 4.1 SEC EDGAR Company Facts API

- **Auth**: None required (User-Agent header: `InvestAgent/1.0 (admin@investagent.app)`)
- **Base URL**: `https://data.sec.gov/api/xbrl/companyfacts`
- **Endpoint**: `GET /CIK{cik}.json` — all XBRL facts for a company
- **Rate limit**: 10 requests per second
- **Filtering**: 10-K forms only (annual filings), deduplicated by fiscal year (keeps latest filing per FY)
- **Unit handling**: USD for financial items, USD/shares for EPS

#### XBRL concept mapping

Each fundamental metric maps to one or more XBRL concept names (fallback chain):

| Metric | Primary Concept | Fallback |
|--------|----------------|----------|
| Revenue | `Revenues` | `RevenueFromContractWithCustomerExcludingAssessedTax` |
| Net Income | `NetIncomeLoss` | — |
| Total Assets | `Assets` | — |
| Total Liabilities | `Liabilities` | — |
| Stockholders' Equity | `StockholdersEquity` | — |
| EPS (diluted) | `EarningsPerShareDiluted` | — |
| Operating Income | `OperatingIncomeLoss` | — |
| Cash from Operations | `NetCashProvidedByUsedInOperatingActivities` | — |
| CapEx | `PaymentsToAcquirePropertyPlantAndEquipment` | — |

The fallback chain handles companies that report under different XBRL taxonomies.

### 4.2 Market data (yfinance)

- **Auth**: None (yfinance scrapes Yahoo Finance)
- **Data**: Daily close prices for each company's stock ticker
- **Time window**: Trailing 2 years from `as_of` date
- **Metrics derived**: 1-year return, 12-month max drawdown, price vs 200-day MA
- **Storage**: `CompanySeries` with `series_name = "equity_close"`

### 4.3 Artefact storage

Same pattern as M2:
- Full EDGAR response stored as one artefact per company (content-hashed, deduplicated)
- Market data artefacts stored per ticker
- All series points reference their source `artefact_id`

## 5. Scoring methodology

### 5.1 Overview

Each company receives a composite score (0–100) computed from three sub-scores. All scoring is deterministic, pinned to `calc_version = "company_v1"`.

### 5.2 Sub-scores and weights

| Sub-score | Weight | Inputs |
|-----------|--------|--------|
| Fundamental | 0.50 | 6 derived financial ratios from EDGAR data |
| Market | 0.30 | 3 equity price metrics (same functions as country module) |
| Industry Context | 0.20 | GICS sector IndustryScore for US from M3 |

### 5.3 Fundamental scoring

#### Derived ratios (computed from raw EDGAR values)

| Ratio | Formula | Higher is better |
|-------|---------|-----------------|
| ROE | net_income / stockholders_equity | Yes |
| Net Margin | net_income / revenue | Yes |
| Debt/Equity | total_liabilities / stockholders_equity | **No** (lower = better) |
| Revenue Growth (YoY) | (rev_latest - rev_prior) / abs(rev_prior) | Yes |
| EPS Growth (YoY) | (eps_latest - eps_prior) / abs(eps_prior) | Yes |
| FCF Yield | (cash_from_ops - capex) / revenue | Yes |

Growth metrics require 2 years of annual data. If either year is missing, the ratio is null.

#### Percentile ranking

For each ratio:
1. Collect values across all 25 companies
2. Percentile-rank from 0.0 (worst) to 1.0 (best)
3. Null values receive median rank (0.5)
4. For debt/equity, **lower** values rank higher

`fundamental_score = mean(6 percentile ranks) × 100`

### 5.4 Market scoring

Reuses the same functions from `app/score/country.py`:
- `compute_1y_return(prices)` — trailing 252-day return
- `compute_max_drawdown(prices)` — worst peak-to-trough in trailing 12 months
- `compute_ma_spread(prices)` — current price vs 200-day SMA

Each metric is percentile-ranked across all 25 companies.

`market_score = mean(3 percentile ranks) × 100`

### 5.5 Industry context

The company's GICS sector IndustryScore (for US, from M3) is used directly as the industry_context_score. If no IndustryScore exists for the sector, defaults to 50.0.

### 5.6 Composite score

`overall = 0.50 × fundamental + 0.30 × market + 0.20 × industry_context`

Range: 0–100. Higher = more investable.

### 5.7 Risk detection

Threshold-based rules applied per company:

| Risk type | Trigger | Severity |
|-----------|---------|----------|
| `high_debt` | Debt/equity > 3.0 | high |
| `low_margin` | Net margin < 0 | medium |
| `revenue_decline` | Revenue growth YoY < -10% | high |
| `market_drawdown` | Max drawdown < -30% | medium |
| `low_score` | Overall score < 30 | high |

Risks are stored in `company_risk_register` with company_id and detected_at.

## 6. Evidence chain

Full evidence lineage:

```
SEC EDGAR API response / yfinance price data
  → Artefact (content-hashed, stored on disk)
    → CompanySeriesPoint (references artefact_id)
      → CompanyScore (references point_ids)
        → DecisionPacket (references score_ids, content includes component_data)
```

The `include_evidence=true` parameter on the summary endpoint returns per-series evidence with artefact IDs and source URLs.

## 7. New database tables

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `companies` | Company registry | ticker (unique), cik (unique), name, gics_code, country_iso2 |
| `company_series` | Time series definitions | company_id, series_name, source, unit, frequency. Unique on (company_id, series_name) |
| `company_series_points` | Individual data points | series_id, artefact_id, date, value. Unique on (series_id, date) |
| `company_scores` | Computed scores | company_id, as_of, calc_version, fundamental_score, market_score, industry_context_score, overall_score, component_data (JSONB), point_ids (JSONB). Unique on (company_id, as_of, calc_version) |
| `company_risk_register` | Flagged risks | company_id, risk_type, severity, description, detected_at, resolved_at, artefact_id |

Migration: `alembic/versions/0004_m4_company_module.py`

## 8. Decision packets

### Company packet structure

```json
{
  "ticker": "AAPL",
  "cik": "0000320193",
  "company_name": "Apple Inc.",
  "gics_code": "45",
  "country_iso2": "US",
  "as_of": "2026-02-01",
  "calc_version": "company_v1",
  "summary_version": "company_summary_v1",
  "scores": {
    "overall": 78.5,
    "fundamental": 85.2,
    "market": 72.0,
    "industry_context": 65.3
  },
  "rank": 3,
  "rank_total": 25,
  "component_data": {
    "fundamental_ratios": {
      "roe": 0.25,
      "net_margin": 0.20,
      "debt_equity": 1.5,
      "revenue_growth": 0.08,
      "eps_growth": 0.12,
      "fcf_yield": 0.15
    },
    "market_metrics": {
      "return_1y": 0.18,
      "max_drawdown": -0.12,
      "ma_spread": 0.05
    },
    "industry_context_score": 65.3
  },
  "risks": [
    {
      "type": "high_debt",
      "severity": "high",
      "description": "Debt/equity ratio of 4.2 exceeds threshold of 3.0"
    }
  ],
  "evidence": null
}
```

When `include_evidence=true`, evidence array is populated:

```json
"evidence": [
  {
    "series": "revenue",
    "value": 394328000000,
    "date": "2023-12-31",
    "artefact_id": "a1b2c3...",
    "source": "sec_edgar",
    "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
  }
]
```

Evidence shows the latest data point per series, with artefact linkage.

## 9. New API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/v1/companies?gics_code=XX` | Yes | Latest scores for all companies, sorted by overall_score desc. Optional GICS sector filter. |
| GET | `/v1/company/{ticker}/summary?as_of=YYYY-MM-DD&include_evidence=false` | Yes | Full decision packet for a single company. |

## 10. New job command

### `company_refresh`

**Params** (JSONB):
- `ticker`: string or null (single company or all 25)
- `as_of`: date string or null (defaults to first of current month)

**Pipeline**:
1. Parse params, determine as_of date
2. Seed data sources (sec_edgar, yfinance)
3. Load company universe config, upsert Company rows
4. For each company (sequential, respecting EDGAR rate limit):
   - Ingest SEC EDGAR XBRL facts → store artefact → upsert series/points per concept
   - Ingest market data (yfinance) → store artefact → upsert equity_close series/points
5. Score all companies in batch (percentile ranking requires the full set)
   - If ticker filter was used, still loads all companies for fair ranking
6. Delete old scores for same as_of + calc_version, insert new scores
7. Detect risks for each company
8. Build decision packets for each company
9. Commit; store artefact_ids and packet_ids on job

**Classification**: Heavy job (uses concurrency slot)

**Single-company support**: When `ticker` is provided, only that company's data is re-ingested, but all companies are re-scored together to maintain fair percentile ranking.

## 11. Frontend pages

### Companies dashboard (`/companies`)
- Ranked table: rank, company name (linked), ticker, GICS sector, overall score, fundamental score, market score
- GICS sector filter dropdown (all 11 sectors)
- "Refresh Companies" button → submits `company_refresh` job
- Each row links to company detail page
- Empty state prompts user to run a refresh

### Company detail (`/companies/{ticker}`)
- Score cards: overall, fundamental (50%), market (30%), industry context (20%)
- Risk flags section with severity color-coding (red for high, yellow for medium)
- Two-column layout:
  - Fundamental Ratios: ROE, net margin, debt/equity, revenue growth, EPS growth, FCF yield (formatted as percentages or multipliers)
  - Market Metrics: 1-year return, max drawdown, MA spread, industry context score
- Evidence Chain table (when available): series, value, date, source, artefact ID
- Tier badge (Top/Mid/Bottom based on rank position)
- Metadata footer: calc_version and summary_version
- Back link to Companies list

### Dashboard update
- Top 5 companies preview on the main dashboard page (rank, name, ticker, score)

### Navigation
- "Companies" link added to NavBar (between Dashboard and Industries)

## 12. Config file

`config/company_universe_v1.json` contains:
- `companies` array: 25 entries with ticker, cik, name, gics_code, country_iso2
- `edgar_concepts` mapping: 9 metric names to XBRL concept name arrays (fallback chains)
- CIK values are 10-digit zero-padded strings

## 13. Acceptance criteria

- [x] `company_refresh` job completes for all 25 companies
- [x] Job logs show progress for each company (EDGAR ingest, market data, scoring)
- [x] `GET /v1/companies` returns 25 companies with scores 0–100
- [x] `GET /v1/company/AAPL/summary` returns a valid decision packet
- [x] `GET /v1/company/AAPL/summary?include_evidence=true` includes artefact references
- [x] All scores are deterministic (same inputs → same outputs)
- [x] No unstored facts or invented narrative in any response
- [x] Every series point references an artefact_id
- [x] Every score references the point_ids used
- [x] Every packet references the score_ids used
- [x] EDGAR fallback concept chains work (e.g., Revenues → RevenueFromContractWithCustomer...)
- [x] 10-K filtering correctly excludes 10-Q forms
- [x] Fiscal year deduplication keeps latest filing per year
- [x] Companies table and detail pages render correctly
- [x] All tests pass (`pytest -q` — 122 tests including 24 company-specific)
- [x] Frontend builds clean (`npm run build` — 56 modules)

## 14. Updated open items

### Resolved
- [x] Company data source: SEC EDGAR Company Facts API (free, XBRL)
- [x] Market data for companies: yfinance (same as country module)
- [x] Scoring weights: 50/30/20 fundamental/market/industry
- [x] Company universe: 25 US companies across all 11 GICS sectors

### Still open
- [ ] Charting library (Recharts vs D3)
- [ ] Pro tier pricing
- [ ] Free tier quotas for company_refresh
- [ ] Non-US company filings (post-v1 expansion)
- [ ] OpenFIGI identifier mapping
- [ ] `universe_refresh` job command (batch refresh for user watchlist)
- [ ] `backfill` job command (historical filings/series)
- [ ] `packet_build` job command (rebuild packets without re-ingesting)
- [ ] Comparison views (side-by-side company comparison)
- [ ] User-configurable company watchlists
- [ ] Per-user company universes
