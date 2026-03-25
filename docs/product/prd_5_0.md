# PRD 5.0 — Universe Expansion + Recommendations

**Product**: investagent.app
**Version**: 5.0 (incremental, builds on PRD 4.0)
**Date**: 2026-03-01
**Status**: Complete
**Milestone**: 5

---

## 1. What this PRD covers

This document specifies two interconnected features: (A) expanding the company universe from 25 US companies to ~150 companies across all 10 investable countries, and (B) introducing a Recommendations view that combines country, industry, and company scores into actionable Buy/Sell/Hold classifications.

The underlying thesis: country scores tell you *where* to invest, industry scores tell you *what sector*, company scores tell you *which stock*. The Recommendations view is where all three layers converge.

For the foundation, see [PRD 1.0](prd_1_0.md). For country, industry, and company modules, see PRDs [2.0](prd_2_0.md), [3.0](prd_3_0.md), [4.0](prd_4_0.md).

## 2. Decisions made since PRD 4.0

| Decision | Detail |
|----------|--------|
| International fundamentals source | **yfinance financial statements** — `ticker.income_stmt`, `ticker.balance_sheet`, `ticker.cashflow`. Unreliable for some stocks (empty DataFrames); graceful degradation when missing. |
| Recommendation methodology | **Weighted composite**: 20% country + 20% industry + 60% company → threshold into Buy/Hold/Sell. |
| Recommendation storage | **Computed on-the-fly** from existing stored scores. No new DB table — deterministic function of three scores. |
| Universe size | **~150 companies**: ~50 US (EDGAR), ~100 international (yfinance fundamentals). |

## 3. Company universe v2

~150 companies across 10 countries, configured in `config/company_universe_v2.json`.

### Target distribution

| Country | Count | Fundamentals Source | Ticker Format |
|---------|-------|-------------------|---------------|
| US | ~50 | SEC EDGAR (XBRL) | `AAPL` |
| GB | ~15 | yfinance | `SHEL.L` |
| JP | ~15 | yfinance | `7203.T` |
| CA | ~10 | yfinance | `RY.TO` |
| AU | ~10 | yfinance | `BHP.AX` |
| DE | ~10 | yfinance | `SAP.DE` |
| FR | ~10 | yfinance | `MC.PA` |
| CH | ~8 | yfinance | `NESN.SW` |
| SE | ~7 | yfinance | `VOLV-B.ST` |
| NL | ~5 | yfinance | `ASML.AS` |

All companies also use yfinance for daily stock price data (market metrics).

### Config structure

Each company entry includes:
- `ticker` — yfinance-compatible ticker symbol (with exchange suffix for non-US)
- `cik` — 10-digit zero-padded SEC CIK (US only; null for international)
- `name` — Company name
- `gics_code` — GICS sector code (links to Industry scoring from M3)
- `country_iso2` — ISO2 country code (links to Country scoring from M2)

## 4. Data sources

### 4.1 SEC EDGAR (US companies — unchanged from M4)

Same as PRD 4.0: Company Facts API with XBRL concept extraction, 10-K annual filings, fallback concept chains.

### 4.2 yfinance financial statements (international companies — new)

- **API**: `yfinance.Ticker(symbol)` with `.income_stmt`, `.balance_sheet`, `.cashflow` properties
- **Format**: pandas DataFrames with dates as columns and financial items as rows
- **Frequency**: Annual financial statements
- **Reliability**: Variable. Major companies on major exchanges generally work. Some return empty DataFrames.
- **Rate limiting**: No formal limit, but yfinance scrapes Yahoo Finance — sequential fetching recommended.

#### Column name mapping (with fallback chains)

| Our metric | DataFrame | Primary column | Fallback(s) |
|------------|-----------|---------------|-------------|
| `revenue` | income_stmt | `Total Revenue` | `Revenue` |
| `net_income` | income_stmt | `Net Income` | `Net Income Common Stockholders` |
| `operating_income` | income_stmt | `Operating Income` | `EBIT` |
| `eps_diluted` | income_stmt | `Diluted EPS` | — |
| `total_assets` | balance_sheet | `Total Assets` | — |
| `total_liabilities` | balance_sheet | `Total Liabilities Net Minority Interest` | `Total Liab` |
| `stockholders_equity` | balance_sheet | `Stockholders Equity` | `Total Stockholders Equity` |
| `cash_from_ops` | cashflow | `Operating Cash Flow` | — |
| `capex` | cashflow | `Capital Expenditure` | — |

**CapEx sign normalization**: yfinance reports capital expenditure as negative; EDGAR reports positive. Normalize to positive (absolute value) for consistent scoring.

### 4.3 yfinance market data (all companies — unchanged from M4)

Reuses existing `fetch_index_history` from `app/ingest/marketdata.py` for daily close prices. Applied to all companies regardless of country.

### 4.4 Artefact storage

- **EDGAR artefacts**: Full JSON response per company (unchanged)
- **yfinance fundamental artefacts**: Serialized financial statement DataFrames as JSON, one artefact per company
- **Source field**: `"sec_edgar"` for US fundamentals, `"yfinance"` for international fundamentals
- All series points reference their source `artefact_id`

## 5. Database changes

### Migration: Make CIK nullable

Non-US companies have no SEC CIK number.

- Alter `companies.cik` column: `NOT NULL` → `NULL`
- Drop existing unique constraint on `cik`
- Add partial unique index: `CREATE UNIQUE INDEX uq_companies_cik ON companies (cik) WHERE cik IS NOT NULL`
  - This preserves CIK uniqueness for US companies while allowing multiple NULLs for international companies.

No new tables required. The recommendation is computed on-the-fly from existing `country_scores`, `industry_scores`, and `company_scores` tables.

## 6. Scoring changes

### 6.1 Fundamentals source filter

The `_load_latest_fundamentals` function currently filters by `CompanySeries.source == "sec_edgar"`. Changed to accept both sources:

```
CompanySeries.source IN ("sec_edgar", "yfinance")
```

Series names are identical regardless of source (revenue, net_income, etc.), so the derived ratio computation works unchanged.

### 6.2 Country-aware industry context lookup

The `_load_industry_context_scores` function currently hardcodes `Country.iso2 == "US"`. Changed to look up each company's own country:

- For AAPL (US, GICS 45): looks up IndustryScore for Info Tech in US
- For 7203.T (JP, GICS 25): looks up IndustryScore for Consumer Disc. in JP

Defaults to 50.0 if no IndustryScore exists for the combination.

### 6.3 Reweighting for missing fundamentals

When yfinance returns no financial statements for a company, all fundamental ratios are null. Rather than penalizing these companies with median fundamental scores, the scoring engine detects the absence and reweights:

| Scenario | Fundamental | Market | Industry Context |
|----------|-------------|--------|-----------------|
| Full data | 50% | 30% | 20% |
| No fundamentals | 0% | 60% | 40% |

Detection: if a company's `fundamentals` dict from `_load_latest_fundamentals` is empty, apply the no-fundamentals weights.

### 6.4 Absolute scoring (replaces percentile ranking)

All scoring layers now use **absolute scoring** instead of percentile ranking. Each metric is scored independently via clamped linear interpolation between fixed thresholds, producing a 0-100 score that is **universe-independent** — scoring one company gives the same result as scoring 150.

**Why**: Percentile ranking forced a zero-sum distribution centered at 50, making it nearly impossible for composite scores to exceed 70 (the Buy threshold). In a strong economy where most companies are performing well, scores should reflect that reality rather than forcing half the universe below average.

**Core function** (`app/score/absolute.py`):
```python
def absolute_score(value, floor, ceiling, higher_is_better=True) -> float:
    # None → 50.0, floor → 0, ceiling → 100, clamped [0, 100]
    # higher_is_better=False swaps floor/ceiling internally
```

**Thresholds by layer**:

#### Country macro thresholds

| Indicator | Floor (0) | Ceiling (100) | Direction |
|-----------|-----------|---------------|-----------|
| gdp_growth | -2.0% | 8.0% | higher=better |
| inflation | 1.0% | 15.0% | lower=better |
| unemployment | 2.0% | 15.0% | lower=better |
| govt_debt_gdp | 20.0% | 200.0% | lower=better |
| current_account_gdp | -8.0% | 10.0% | higher=better |
| fdi_gdp | -1.0% | 8.0% | higher=better |
| reserves | $0B | $500B | higher=better |

#### Market thresholds (shared by country and company)

| Metric | Floor (0) | Ceiling (100) | Direction |
|--------|-----------|---------------|-----------|
| return_1y | -40% | +40% | higher=better |
| max_drawdown | -50% | 0% | higher=better |
| ma_spread | -20% | +20% | higher=better |

#### Company fundamental thresholds

| Ratio | Floor (0) | Ceiling (100) | Direction |
|-------|-----------|---------------|-----------|
| roe | -20% | 30% | higher=better |
| net_margin | -15% | 25% | higher=better |
| debt_equity | 0.0 | 5.0 | lower=better |
| revenue_growth | -20% | 30% | higher=better |
| eps_growth | -30% | 50% | higher=better |
| fcf_yield | -10% | 20% | higher=better |

#### Industry scoring: linear rescale

Industry rubric scores use linear rescale instead of percentile ranking:
```
overall = ((raw_score + N) / (2 * N)) * 100
```
Where N = max_possible (number of indicators for that sector). This produces N*2+1 distinct values (e.g., a sector with 5 indicators produces scores: 0, 10, 20, ..., 100).

#### Version bump

All `calc_version` strings bumped from v1 to v2 (`country_v2`, `industry_v2`, `company_v2`). Old v1 scores in the DB are ignored; v2 scores coexist alongside.

#### Handler simplification

Since absolute scoring is universe-independent, the "load all entities for fair ranking" workaround in country and company handlers is removed. When refreshing a single country or company, only that entity needs to be scored.

## 7. Recommendation methodology

### 7.1 Composite score formula

```
composite = 0.20 × country_score + 0.20 × industry_score + 0.60 × company_score
```

Where:
- `country_score` = latest `CountryScore.overall_score` for the company's `country_iso2` (default 50.0)
- `industry_score` = latest `IndustryScore.overall_score` for the company's `gics_code` + `country_iso2` (default 50.0)
- `company_score` = latest `CompanyScore.overall_score` for the company

### 7.2 Classification thresholds

| Classification | Condition | Color |
|---------------|-----------|-------|
| **Buy** | composite > 70 | Green |
| **Hold** | 40 ≤ composite ≤ 70 | Yellow |
| **Sell** | composite < 40 | Red |

### 7.3 Design: computed on-the-fly

The recommendation is NOT stored in the database. It is computed at query time by joining the latest scores from all three layers. This means:

- No new DB table or migration needed
- If any underlying score changes (country refresh, industry refresh, company refresh), the recommendation automatically reflects the update
- Full determinism: same stored scores always produce same recommendation
- Pinned to `recommendation_version = "recommendation_v1"` for the formula + thresholds

## 8. New API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/v1/recommendations` | Yes | Composite recommendations for all companies |

### Query parameters

| Param | Type | Description |
|-------|------|-------------|
| `classification` | string | Filter: `Buy`, `Hold`, or `Sell` |
| `country_iso2` | string | Filter by country |
| `gics_code` | string | Filter by GICS sector |

### Response format

```json
[
  {
    "ticker": "AAPL",
    "name": "Apple Inc.",
    "country_iso2": "US",
    "gics_code": "45",
    "company_score": 78.5,
    "country_score": 72.0,
    "industry_score": 65.3,
    "composite_score": 74.6,
    "classification": "Buy",
    "rank": 1,
    "rank_total": 150,
    "as_of": "2026-03-01",
    "recommendation_version": "recommendation_v1"
  }
]
```

Sorted by `composite_score` descending.

### Modified endpoint

| Method | Path | Change |
|--------|------|--------|
| GET | `/v1/companies` | Added `country_iso2` query param filter; added `country_iso2` to response items |

## 9. Company refresh handler changes

The `company_refresh` job handler routes data ingestion based on country:

```
For each company:
  if country_iso2 == "US":
    → ingest_edgar_for_company() (existing)
  else:
    → ingest_yfinance_fundamentals_for_company() (new)

  → ingest_market_data_for_company() (existing, all companies)
```

Config path updated from `company_universe_v1.json` to `company_universe_v2.json`.

Job progress logged as "Company 37/150" for better UX with the larger universe.

## 10. Frontend pages

### Recommendations page (`/recommendations`) — NEW

- **Header**: "Recommendations" title
- **Summary cards**: Count of Buy / Hold / Sell recommendations
- **Filters**: Classification dropdown (All/Buy/Hold/Sell), Country dropdown, Sector dropdown
- **Table columns**: Rank, Company, Country, Sector, Composite Score, Company Score, Country Score, Industry Score, Classification badge
- **Classification badges**: Green (Buy), Yellow (Hold), Red (Sell)
- **Sorting**: By composite score descending

### Companies page updates (`/companies`)

- Add country filter dropdown alongside existing sector filter
- Add Country column to table

### Dashboard update (`/dashboard`)

- Add "Top Buy Recommendations" section showing top 5 Buy-classified companies

### Navigation

- Add "Recommendations" link to NavBar

## 11. Version constants

```python
COUNTRY_CALC_VERSION = "country_v2"
INDUSTRY_CALC_VERSION = "industry_v2"
COMPANY_CALC_VERSION = "company_v2"
RECOMMENDATION_VERSION = "recommendation_v1"
RECOMMENDATION_WEIGHTS = {"country": 0.20, "industry": 0.20, "company": 0.60}
RECOMMENDATION_THRESHOLDS = {"buy": 70, "sell": 40}
COMPANY_WEIGHTS_NO_FUNDAMENTALS = {"fundamental": 0.0, "market": 0.60, "industry_context": 0.40}
```

## 12. Acceptance criteria

- [ ] `alembic upgrade head` applies migration (cik nullable)
- [ ] `company_refresh` job processes ~150 companies (US via EDGAR, international via yfinance)
- [ ] `GET /v1/companies` returns ~150 companies with scores
- [ ] `GET /v1/companies?country_iso2=JP` filters to Japanese companies
- [ ] `GET /v1/recommendations` returns all recommendations with composite scores
- [ ] `GET /v1/recommendations?classification=Buy` returns Buy-classified companies only
- [ ] Companies with missing yfinance fundamentals are scored with reweighted formula (market=60%, industry=40%)
- [ ] Industry context scores use correct country (not hardcoded US)
- [ ] Composite formula: 20% country + 20% industry + 60% company is deterministic
- [ ] All scores are deterministic (same inputs → same outputs)
- [ ] Recommendations page renders with classification badges, filters
- [ ] Companies page shows country column and filter
- [ ] Dashboard shows top Buy recommendations
- [ ] All tests pass (`pytest -q`)
- [ ] Frontend builds clean (`npm run build`)

## 13. Known limitations

- **yfinance fundamentals reliability**: Some international companies will return empty financial statements. These companies are scored on market data + industry context only (reweighted). This is logged as a warning during the refresh job.
- **yfinance column naming variance**: Column names in yfinance DataFrames vary by company and region. Fallback chains mitigate this, but some metrics may still be missing for specific companies.
- **CapEx sign convention**: yfinance reports capex as negative, EDGAR as positive. Normalized to positive, but edge cases possible.
- **Sweden market data**: Known issue from M2 (KI-2) — OMXS30 returns no data from yfinance. Swedish companies may also have limited market data.
- **FRED indicators US-centric**: Industry scores for non-US countries lack FRED-sourced indicators (central bank rate, credit spreads, yield curve), receiving neutral signals for those.

## 14. Open items

### Resolved
- [x] International fundamentals source: yfinance financial statements
- [x] Recommendation methodology: weighted composite (20/20/60)
- [x] Recommendation storage: computed on-the-fly

### Still open
- [ ] Charting library (Recharts vs D3)
- [ ] Pro tier pricing
- [ ] Free tier quotas for company_refresh and recommendations
- [ ] User-configurable company watchlists
- [ ] Historical recommendation tracking (time series of classifications)
- [ ] Company comparison views
- [ ] PDF export of recommendations
