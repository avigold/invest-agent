# PRD 2.0 — Country Module v1

**Product**: investagent.app
**Version**: 2.0 (incremental, builds on PRD 1.0)
**Date**: 2026-02-28
**Status**: Complete
**Milestone**: 2

---

## 1. What this PRD covers

This document specifies the Country Module — the first real research pipeline in Invest Agent. It describes the data sources, ingestion pipeline, scoring methodology, decision packet structure, API endpoints, and frontend pages added in Milestone 2.

For the foundation (auth, billing, job system, frontend skeleton), see [PRD 1.0](prd_1_0.md).

## 2. Decisions made since PRD 1.0

| Open item from PRD 1.0 | Decision |
|-------------------------|----------|
| Session management (JWT vs session cookie) | **JWT httpOnly cookies** — set on OAuth callback, 7-day expiry, cleared on logout |
| Investable countries list | **US, GB, CA, AU, JP, DE, FR, NL, CH, SE** (10 countries) |
| EOD market data provider | **yfinance for MVP** — free, no API key. Interface designed for swap to EODHD later. |
| GDELT stability index transform | **Implemented in M2** — GDELT DOC 2.0 API with theme-based instability query, monthly averaging, inverted to 0-1 stability score. Fallback to 0.5 on API failure. |
| Govt debt/GDP data source | **Switched from World Bank to IMF WEO** — World Bank `GC.DOD.TOTL.GD.ZS` (central govt only) was missing data for 5/10 countries. Replaced with IMF `GGXWDG_NGDP` (general govt gross debt) which covers all 10. |
| Charting library | Deferred — M2 frontend uses simple color-coded tables and score cards. Charts added in M3. |
| Exact Free tier monthly quotas | `country_refresh`: 5/month (set in M1 plan gating) |

## 3. Country universe

10 investable countries, configured in `config/investable_countries_v1.json`:

| ISO2 | Country | Equity Index |
|------|---------|-------------|
| US | United States | S&P 500 (^GSPC) |
| GB | United Kingdom | FTSE 100 (^FTSE) |
| CA | Canada | S&P/TSX (^GSPTSE) |
| AU | Australia | ASX 200 (^AXJO) |
| JP | Japan | Nikkei 225 (^N225) |
| DE | Germany | DAX (^GDAXI) |
| FR | France | CAC 40 (^FCHI) |
| NL | Netherlands | AEX (^AEX) |
| CH | Switzerland | SMI (^SSMI) |
| SE | Sweden | OMXS30 (OMXS30) |

## 4. Data sources

### 4.1 World Bank Indicators API
- **Auth**: None required
- **Base URL**: `https://api.worldbank.org/v2/`
- **Indicators ingested per country**:

| Series name | Indicator code | Unit | Direction |
|-------------|---------------|------|-----------|
| GDP | NY.GDP.MKTP.CD | USD | — |
| GDP growth | NY.GDP.MKTP.KD.ZG | % | Higher is better |
| Inflation | FP.CPI.TOTL.ZG | % | Lower is better |
| Unemployment | SL.UEM.TOTL.ZS | % | Lower is better |
| Current account/GDP | BN.CAB.XOKA.GD.ZS | % | Higher is better |
| FDI/GDP | BX.KLT.DINV.WD.GD.ZS | % | Higher is better |
| Reserves | FI.RES.TOTL.CD | USD | Higher is better |

- **Frequency**: Annual (World Bank data typically lags 1-2 years)
- **Time window**: 2015 to present
- **Note**: `govt_debt_gdp` was removed from World Bank — see IMF section below

### 4.1b IMF World Economic Outlook (WEO) API
- **Auth**: None required
- **Base URL**: `https://www.imf.org/external/datamapper/api/v1/`
- **Country codes**: ISO 3166-1 alpha-3 (mapped from our ISO2 codes)
- **Indicators ingested per country**:

| Series name | Indicator code | Unit | Direction |
|-------------|---------------|------|-----------|
| Govt debt/GDP | GGXWDG_NGDP | % | Lower is better |

- **Frequency**: Annual (updated semi-annually with April/October WEO releases)
- **Time window**: 2015 to present
- **Why IMF instead of World Bank**: The World Bank indicator `GC.DOD.TOTL.GD.ZS` measures *central* government debt only and returns null for JP, DE, FR, NL, SE. The IMF indicator measures *general* government gross debt (central + state/local + social security) and covers all 10 countries. This is the standard measure used in economic analysis.

### 4.2 FRED API
- **Auth**: API key required (free registration at fredaccount.stlouisfed.org)
- **Base URL**: `https://api.stlouisfed.org/fred/`
- **Rate limit**: 120 requests/minute
- **Series** (US-centric global risk proxies, applied to all countries):

| Series ID | Name | Frequency |
|-----------|------|-----------|
| FEDFUNDS | Federal Funds Rate | Monthly |
| BAMLC0A4CBBB | US HY Spread | Daily |
| BAA10Y | Baa-10Y Spread | Daily |
| DGS10 | 10Y Treasury Yield | Daily |
| T10Y2Y | Yield Curve (10Y-2Y) | Daily |

- **Graceful degradation**: If `FRED_API_KEY` is not set, FRED ingest is skipped. Scoring still works — those series simply have no data points.

### 4.3 Equity index data (yfinance)
- **Auth**: None (yfinance scrapes Yahoo Finance)
- **Data**: Daily OHLCV for each country's equity index
- **Time window**: Trailing 2 years from run date
- **Metrics derived**: 1-year return, 12-month max drawdown, price vs 200-day MA
- **Future**: Interface designed for swap to EODHD (paid, reliable)

### 4.4 GDELT political stability
- **Auth**: None required
- **API**: GDELT DOC 2.0 API (`https://api.gdeltproject.org/api/v2/doc/doc`)
- **Query**: `sourcecountry:{FIPS} (theme:PROTEST OR theme:ARMEDCONFLICT OR theme:TERROR OR theme:POLITICAL_TURMOIL)`
- **Mode**: `timelinevol` — returns daily "Volume Intensity" (article volume as % of total global volume)
- **Format**: CSV with columns `Date,Series,Value`
- **Time span**: Trailing 3 months
- **Country codes**: GDELT uses FIPS 10-4 codes, mapped from ISO2 (e.g., GB→UK, JP→JA, DE→GM, AU→AS, CH→SZ, SE→SW)
- **Computation**:
  1. Filter CSV rows to the target `as_of` month
  2. `monthly_instability = mean(daily Volume Intensity values)`
  3. `stability_value = 1.0 - (monthly_instability / 10.0)`, clamped to [0, 1]
  4. Scoring engine: `stability_score = stability_value × 100`
- **Rate limiting**: 3-second delay between country fetches; retry up to 3 times with 90s timeout
- **Fallback**: If API fails or returns no data, uses 0.5 (neutral) and logs warning
- **Evidence**: Raw CSV stored as artefact with source URL

## 5. Scoring methodology

### 5.1 Overview

Each country receives a composite score (0-100) computed from three sub-scores via percentile ranking across the 10-country universe. All scoring is deterministic and pinned to `calc_version = "country_v1"`.

### 5.2 Sub-scores

| Sub-score | Weight | Inputs |
|-----------|--------|--------|
| Macro | 0.45 | 7 indicators: GDP growth, inflation, unemployment (World Bank); govt debt/GDP (IMF WEO); current account/GDP, FDI/GDP, reserves (World Bank) |
| Market | 0.35 | 3 equity index metrics (1Y return, max drawdown, price vs 200-day MA) |
| Stability | 0.20 | GDELT DOC API instability volume, inverted to 0-1 stability index |

### 5.3 Percentile ranking

For each indicator within a sub-score:
1. Get the latest available value for each of the 10 countries
2. Rank countries from 0.0 (worst) to 1.0 (best), with ties receiving average rank
3. If a country has no data for an indicator, assign median rank (0.5)

Sub-score = mean(percentile_ranks) × 100

### 5.4 Composite score

`overall = 0.45 × macro + 0.35 × market + 0.20 × stability`

Range: 0-100. Higher = more investable.

### 5.5 Risk detection

Threshold-based rules applied per country:

| Risk type | Trigger | Severity |
|-----------|---------|----------|
| `high_inflation` | Inflation > 5% | medium (>5%), high (>10%) |
| `high_debt` | Govt debt/GDP > 100% | medium (>100%), high (>150%) |
| `market_drawdown` | Max drawdown > 20% | medium (>20%), high (>30%) |
| `low_overall_score` | Overall score < 30 | high |

Risks are stored in `country_risk_register` with artefact references.

## 6. Evidence chain

Every score is fully traceable:

```
Raw API response
  → Artefact (content-hashed, stored on disk, referenced in DB)
    → Country series point (references artefact_id)
      → Country score (references point_ids used)
        → Decision packet (references score_ids used)
```

The `include_evidence=true` query parameter on the summary endpoint returns the full lineage for every data point.

### Artefact storage
- **Dev**: Filesystem at `./data/artefacts/{artefact_id}.json` (gitignored)
- **DB fields**: source metadata, fetch time window, SHA-256 content hash, storage URI, size
- **Deduplication**: If content hash matches an existing artefact for the same source, skip re-write (idempotent)
- **Prod** (future): S3-compatible storage

## 7. Decision packets

A decision packet is a self-contained JSON document assembled strictly from stored data. No invented narrative. No unstored facts.

### Country packet structure

```json
{
  "iso2": "US",
  "country_name": "United States",
  "as_of": "2026-02-01",
  "calc_version": "country_v1",
  "summary_version": "country_summary_v1",
  "scores": {
    "overall": 72.5,
    "macro": 68.3,
    "market": 81.2,
    "stability": 50.0
  },
  "rank": 3,
  "rank_total": 10,
  "component_data": {
    "gdp_growth": {"value": 2.1, "unit": "%", "date": "2024", "percentile": 0.6},
    "inflation": {"value": 3.4, "unit": "%", "date": "2024", "percentile": 0.7},
    "..."
  },
  "market_metrics": {
    "return_1y": {"value": 0.12, "percentile": 0.8},
    "max_drawdown": {"value": -0.08, "percentile": 0.9},
    "ma_spread": {"value": 0.05, "percentile": 0.7}
  },
  "risks": [
    {"type": "high_inflation", "severity": "medium", "description": "Inflation at 5.2%"}
  ],
  "evidence": null
}
```

When `include_evidence=true`, the `evidence` field is populated:

```json
"evidence": [
  {
    "series": "gdp_growth",
    "value": 2.1,
    "date": "2024",
    "artefact_id": "a1b2c3...",
    "source": "world_bank",
    "source_url": "https://api.worldbank.org/v2/country/US/indicator/NY.GDP.MKTP.KD.ZG"
  }
]
```

## 8. New database tables

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `data_sources` | Registry of external data providers | name (unique), base_url, requires_auth |
| `artefacts` | Raw API response storage metadata | data_source_id, content_hash (SHA-256), storage_uri, fetch time window |
| `countries` | Investable country registry | iso2 (unique), iso3, name, equity_index_symbol |
| `country_series` | Time series definitions per country | country_id, series_name, source, indicator_code |
| `country_series_points` | Individual data points | series_id, artefact_id, date, value |
| `country_scores` | Computed scores per country per period | country_id, as_of, calc_version, macro/market/stability/overall scores, point_ids |
| `country_risk_register` | Flagged risks | country_id, risk_type, severity, artefact_id |
| `decision_packets` | Assembled decision documents | packet_type, entity_id, as_of, summary_version, content (JSONB) |

## 9. New API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/v1/countries` | Yes | Latest scores for all 10 countries, sorted by overall score desc |
| GET | `/v1/country/{iso2}/summary` | Yes | Full decision packet. Query params: `as_of` (date), `include_evidence` (bool) |

## 10. New job command

### `country_refresh`

**Params** (JSONB):
- `iso2`: string or null (single country or all 10)
- `as_of`: date string or null (defaults to first of current month)

**Pipeline** (orchestrated in handler, each step logged for SSE):
1. Seed data sources (world_bank, imf, fred, yfinance, gdelt)
2. Upsert countries from config
3. For each country: ingest World Bank → IMF WEO → FRED → market data → GDELT
4. Compute scores for all countries (percentile ranking requires all)
5. Detect risks
6. Build decision packets
7. Store artefact_ids and packet_id on job row

**Classification**: Heavy job (uses concurrency slot)

## 11. Frontend pages

### Country dashboard (`/countries`)
- Ranked table: rank, country name, overall/macro/market/stability scores, as_of
- Color-coded scores: green (>70), yellow (40-70), red (<40)
- "Refresh Countries" button → submits `country_refresh` job
- Each row links to country detail page

### Country detail (`/countries/{iso2}`)
- Score cards for overall, macro, market, stability
- Component data table (indicator, value, percentile rank)
- Risk register (if any risks detected)
- Evidence table (when available — artefact source, date, source URL)
- Back link to country dashboard

### Dashboard update
- Top 3 countries preview on the main dashboard page

### Navigation
- "Countries" link added to NavBar

## 12. Config file

`config/investable_countries_v1.json` contains:
- Country list with ISO codes, names, equity index symbols
- World Bank indicator mappings (6 indicators)
- IMF WEO indicator mappings (1 indicator: govt_debt_gdp)
- FRED series metadata (US-centric global risk proxies)
- Scoring weights

## 13. Updated open items

### Resolved
- [x] Session management: JWT httpOnly cookies
- [x] Investable countries list: US, GB, CA, AU, JP, DE, FR, NL, CH, SE
- [x] EOD market data provider: yfinance for MVP
- [x] GDELT stability: real implementation via DOC 2.0 API (theme-based instability volume)
- [x] Govt debt/GDP data gap: switched from World Bank (5/10 coverage) to IMF WEO (10/10 coverage)

### Still open
- [ ] Charting library (Recharts vs D3) — deferred, M2 uses tables and score cards
- [ ] FRED API key — user needs to register at fredaccount.stlouisfed.org (optional for M2)
- [ ] Pro tier pricing
- [ ] Exact Free tier quotas for industry/company commands (M3/M4)
- [ ] Country data auto-refresh scheduling (daily cron for Pro users)

## 14. Acceptance criteria

- [x] `country_refresh` job completes successfully for all 10 countries
- [x] Job logs show progress for each ingest/score/packet step (polling-based log viewer)
- [x] `GET /v1/countries` returns 10 countries with scores 0-100
- [x] `GET /v1/country/US/summary` returns a valid decision packet
- [x] `GET /v1/country/US/summary?include_evidence=true` includes artefact references
- [x] All scores are deterministic (same inputs → same outputs)
- [x] No unstored facts or invented narrative in any response
- [x] Every series point references an artefact_id
- [x] Every score references the point_ids used
- [x] Every packet references the score_ids used
- [x] Country dashboard displays ranked table with color-coded scores
- [x] Country detail page shows score breakdown, risks, and evidence
- [x] All new tests pass (`pytest -q` — 85 tests)
- [ ] E2E script (`python -m scripts.e2e_country`) passes

## 15. Known issues

### KI-1: GDELT stability score biased by English-language media volume

**Severity**: Medium — affects relative ranking but does not break scoring pipeline

The GDELT DOC API's "Volume Intensity" metric measures article volume as a percentage of total global coverage. Countries that generate more English-language news (especially the US) show significantly higher instability volume — not because they are less stable, but because instability-themed reporting (protest, conflict, terrorism, political turmoil) is a larger share of their total coverage.

**Impact**: The US scores 73.3 on stability while all other countries in the universe score 92-99. This depresses the US overall score by ~5 points relative to a normalized baseline.

**Possible mitigations** (not yet implemented):
1. **Percentile-rank stability** across the 10-country universe instead of using the raw 0-1 value — consistent with how macro and market sub-scores work
2. **Adjust the normalization cap** (currently dividing by 10.0) per-country or use a log transform to compress the range
3. **Switch to a different GDELT metric** (e.g., tone-based instead of volume-based) that is less sensitive to absolute coverage levels

### KI-2: Sweden market data missing (yfinance)

**Severity**: Low — Sweden gets median percentile rank (50.0) for all three market metrics

The OMXS30 ticker (`OMXS30`) returns no data from yfinance. All three market metrics (1Y return, max drawdown, MA spread) are null. Sweden receives a default 0.5 percentile rank on each, which is neither a penalty nor a bonus.

**Possible fix**: Try alternative ticker symbols (e.g., `^OMX`, `^OMXS30`, `OMXS30.ST`) or switch to a paid market data provider for non-US indices.
