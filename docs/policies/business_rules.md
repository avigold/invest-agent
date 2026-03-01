# Business Rules — investagent.app

Last updated: 2026-03-01

This document describes the scoring methodology, business rules, thresholds, and behavioral logic of the Invest Agent platform.

---

## 1. Scoring overview

All scoring uses **absolute scoring** — each entity is scored on its own merits against fixed thresholds, not relative to peers. This means adding or removing entities does not change existing scores.

### 1.1 Absolute scoring function

Every numeric indicator is scored 0–100 via clamped linear interpolation:

```
score = clamp((value - floor) / (ceiling - floor), 0, 1) * 100
```

- Values at or below `floor` → 0
- Values at or above `ceiling` → 100
- Values between → linear interpolation
- Missing values (`None`) → default 50.0
- When `higher_is_better = False`, floor and ceiling are swapped internally

**Source**: `app/score/absolute.py`

---

## 2. Country scoring

**Versions**: `country_v2` (calc), `country_summary_v2` (summary)

### 2.1 Formula

```
overall = 0.50 * macro + 0.40 * market + 0.10 * stability
```

### 2.2 Macro sub-score

Average of 10 indicators, each scored 0–100 via absolute thresholds:

| Indicator | Floor | Ceiling | Higher is better |
|---|---|---|---|
| gdp_growth | -2.0% | 8.0% | Yes |
| inflation | 1.0% | 15.0% | No |
| unemployment | 2.0% | 15.0% | No |
| govt_debt_gdp | 20.0% | 200.0% | No |
| current_account_gdp | -8.0% | 10.0% | Yes |
| fdi_gdp | -1.0% | 8.0% | Yes |
| reserves | $0 | $500B | Yes |
| gdp_per_capita | $5,000 | $100,000 | Yes |
| market_cap_gdp | 20.0% | 200.0% | Yes |
| household_consumption_pc | $10,000 | $45,000 | Yes |

### 2.3 Market sub-score

Average of 3 metrics, each scored 0–100:

| Metric | Floor | Ceiling | Higher is better |
|---|---|---|---|
| return_1y | -40% | +40% | Yes |
| max_drawdown | -50% | 0% | Yes |
| ma_spread (vs 200-day MA) | -20% | +20% | Yes |

**Market metric calculations:**
- **1-year return**: `(latest_close / close_252_days_ago) - 1.0`
- **Max drawdown**: Rolling peak-to-trough drawdown over the full price history
- **MA spread**: `(current_close / 200-day SMA) - 1.0`

### 2.4 Stability sub-score

GDELT-derived political stability index (0–1) scaled to 0–100. Defaults to 50.0 if missing.

### 2.5 Data sources

| Source | Indicators | Freshness window |
|---|---|---|
| World Bank | 6 macro indicators | 30 days |
| IMF WEO | govt_debt_gdp | 30 days |
| FRED | fedfunds, hy_spread, yield_curve (US only) | 1 day |
| yfinance | Equity index prices | 4 hours |
| GDELT | Stability index | 7 days |

### 2.6 Country risk detection

| Risk type | Threshold | Severity |
|---|---|---|
| high_inflation | > 10% | HIGH |
| high_inflation | > 5% | MEDIUM |
| high_debt | > 150% of GDP | HIGH |
| high_debt | > 100% of GDP | MEDIUM |
| market_drawdown | < -30% | HIGH |
| market_drawdown | < -20% | MEDIUM |
| low_overall_score | < 30 | HIGH |

### 2.7 Investable countries

10 countries configured in `config/investable_countries_v1.json`:

US, GB, CA, AU, JP, DE, FR, NL, CH, SE

---

## 3. Industry scoring

**Versions**: `industry_v3` (calc), `industry_summary_v3` (summary)

### 3.1 Formula

Each industry is scored per country using a rubric of macro sensitivities:

```
overall = weighted_average(indicator_scores)
```

Each indicator is scored 0–100 via absolute thresholds. Weights default to 1.0. The `favorable_when` direction on each indicator controls whether the score is used as-is or inverted.

### 3.2 Industry indicator thresholds

| Indicator | Floor | Ceiling |
|---|---|---|
| gdp_growth | -2.0% | 8.0% |
| inflation | 1.0% | 15.0% |
| unemployment | 2.0% | 15.0% |
| govt_debt_gdp | 20.0% | 200.0% |
| current_account_gdp | -8.0% | 10.0% |
| fdi_gdp | -1.0% | 8.0% |
| fedfunds (central bank rate) | 0.0% | 10.0% |
| hy_spread | 200 bps | 1000 bps |
| yield_curve (10y-2y) | -100 bps | 300 bps |
| stability | 0.0 | 1.0 |

### 3.3 GICS sectors (11)

| Code | Sector | Key sensitivities |
|---|---|---|
| 10 | Energy | Pro-cyclical (GDP, inflation), stability |
| 15 | Materials | Pro-cyclical, FDI-driven |
| 20 | Industrials | Highly cyclical, rate-sensitive (yield curve) |
| 25 | Consumer Discretionary | Cyclical, low rates & tight spreads |
| 30 | Consumer Staples | Defensive, hurt by inflation & high rates |
| 35 | Health Care | Govt debt (payer pressure), discount rates |
| 40 | Financials | Yield curve dominant (net interest margin) |
| 45 | Information Technology | Pro-cyclical, rate-sensitive (growth duration) |
| 50 | Communication Services | Pro-cyclical, stability (concession risk) |
| 55 | Utilities | Rate-sensitive (bond proxy), hurt by inflation |
| 60 | Real Estate | Highly rate-sensitive (REIT valuations) |

### 3.4 Industry risk detection

| Risk type | Threshold | Severity |
|---|---|---|
| macro_headwinds | Score < 15 | HIGH |
| macro_headwinds | Score 15–30 | MEDIUM |
| all_signals_negative | All indicators unfavorable (< 30) | HIGH |

---

## 4. Company scoring

**Versions**: `company_v3` (calc), `company_summary_v3` (summary)

### 4.1 Formula

```
With fundamentals:    overall = 0.60 * fundamental + 0.40 * market
Without fundamentals: overall = 0.00 * fundamental + 1.00 * market
```

Companies lacking fundamental data (no EDGAR/yfinance filings) are scored on market metrics only.

### 4.2 Fundamental sub-score

Average of 6 financial ratios, each scored 0–100:

| Ratio | Floor | Ceiling | Higher is better |
|---|---|---|---|
| ROE | -20% | 30% | Yes |
| Net margin | -15% | 25% | Yes |
| Debt/equity | 0.0x | 5.0x | No |
| Revenue growth (YoY) | -20% | 30% | Yes |
| EPS growth (YoY) | -30% | 50% | Yes |
| FCF yield | -10% | 20% | Yes |

**Ratio calculations:**
```
ROE = net_income / stockholders_equity
Net margin = net_income / revenue
Debt/equity = total_liabilities / stockholders_equity
Revenue growth = (latest - prior_year) / abs(prior_year)
EPS growth = (latest - prior_year) / abs(prior_year)
FCF yield = (cash_from_ops - capex) / revenue
```

Fundamental data loads the 2 most recent annual values per metric (for YoY growth). Sources: SEC EDGAR for US companies, yfinance for international.

### 4.3 Market sub-score

Same 3 metrics and thresholds as country market scoring (return_1y, max_drawdown, ma_spread).

### 4.4 Company risk detection

| Risk type | Threshold | Severity |
|---|---|---|
| high_debt | debt/equity > 3.0 | HIGH |
| low_margin | net margin < 0 | MEDIUM |
| revenue_decline | revenue growth < -10% YoY | HIGH |
| market_drawdown | max drawdown < -30% | MEDIUM |
| low_score | overall score < 30 | HIGH |

### 4.5 Data sources

| Source | Data | Freshness window |
|---|---|---|
| SEC EDGAR | US company fundamentals (XBRL) | 30 days |
| yfinance fundamentals | International company fundamentals | 30 days |
| yfinance market | Equity close prices | 4 hours |

### 4.6 EDGAR concept mapping

Maps XBRL concept names to financial metrics:

| Metric | XBRL concepts (tried in order) |
|---|---|
| revenue | Revenues, RevenueFromContractWithCustomerExcludingAssessedTax |
| net_income | NetIncomeLoss |
| total_assets | Assets |
| total_liabilities | Liabilities |
| stockholders_equity | StockholdersEquity |
| eps_diluted | EarningsPerShareDiluted |
| operating_income | OperatingIncomeLoss |
| cash_from_ops | NetCashProvidedByUsedInOperatingActivities |
| capex | PaymentsToAcquirePropertyPlantAndEquipment |

---

## 5. Recommendations

**Version**: `recommendation_v2`

### 5.1 Composite score

```
composite = 0.20 * country_score + 0.20 * industry_score + 0.60 * company_score
```

**Effective weights after decomposition:**
- 36% fundamental (0.60 company * 0.60 fundamental)
- 24% market (0.60 company * 0.40 market)
- 20% country
- 20% industry

### 5.2 Classification

| Classification | Condition |
|---|---|
| Buy | composite > 70 |
| Hold | 40 <= composite <= 70 |
| Sell | composite < 40 |

### 5.3 Inputs

- **Country score**: Latest `CountryScore.overall_score` for the company's `country_iso2`
- **Industry score**: Latest `IndustryScore.overall_score` for the company's GICS sector in its country. Defaults to 50.0 if no GICS code or no industry score found.
- **Company score**: Latest `CompanyScore.overall_score`

Recommendations are computed on-the-fly from stored scores — not pre-persisted.

---

## 6. Company universe

### 6.1 Source of truth

The database is the authoritative source for which companies to process. The JSON config (`config/company_universe_v2.json`) is a seed — companies are upserted from it on each `company_refresh`. Companies can also exist only in the DB with `config_version="user_added"`.

### 6.2 Adding companies

**Search**: SEC `company_tickers.json` cache (~13K US public companies). Cached in-memory with 24h TTL.

**Bulk add**: yfinance screener API (`yf.screen()`) returns US equities pre-sorted by market cap descending, 250 per page. No per-ticker lookups needed.

**Add flow:**
1. Fetch screener pages until N new companies are found (skipping those already in DB)
2. Cross-reference SEC ticker cache for CIK
3. Skip tickers whose CIK already exists in DB (duplicate share classes, e.g. GOOG vs GOOGL)
4. Insert with `config_version="user_added"`
5. Enrich GICS codes via yfinance
6. Run ingest + score + risk detection + packet building for new companies only

### 6.3 CIK deduplication

The `companies` table has a partial unique index on CIK where CIK is not null. Companies with duplicate CIKs (multiple share classes) are skipped — the existing share class is sufficient for scoring.

### 6.4 GICS enrichment

Both `company_refresh` and `add_companies_by_market_cap` backfill missing GICS codes (where `gics_code=""`) by calling `yfinance.Ticker(symbol).info` and mapping the sector text to a 2-digit GICS code.

### 6.5 GICS sector mapping

| yfinance sector | GICS code |
|---|---|
| Energy | 10 |
| Basic Materials / Materials | 15 |
| Industrials | 20 |
| Consumer Cyclical / Consumer Discretionary | 25 |
| Consumer Defensive / Consumer Staples | 30 |
| Healthcare / Health Care | 35 |
| Financial Services / Financials | 40 |
| Technology / Information Technology | 45 |
| Communication Services | 50 |
| Utilities | 55 |
| Real Estate | 60 |

### 6.6 Country mapping

| yfinance country | ISO2 |
|---|---|
| United States | US |
| United Kingdom | GB |
| Japan | JP |
| Canada | CA |
| Australia | AU |
| Germany | DE |
| France | FR |
| Switzerland | CH |
| Sweden | SE |
| Netherlands | NL |

Default: US if unmapped.

---

## 7. Ranking

Ranks are computed within decision packets. A company's rank is its position (1 = highest) among all companies scored for the same `as_of` date and `calc_version`.

The `add_companies_by_market_cap` handler loads all scores from the DB before building packets, ensuring ranks reflect global position — not just the batch.

The `company_refresh` handler scores all companies together, so ranks are naturally global.

---

## 8. Job system

### 8.1 Job commands

| Command | Type | Description |
|---|---|---|
| country_refresh | Heavy | Ingest country data, score, build packets |
| industry_refresh | Heavy | Score industries per country, build packets |
| company_refresh | Heavy | Ingest company data, score, build packets |
| universe_refresh | Heavy | Batch refresh all layers |
| backfill | Heavy | Historical data backfill |
| data_sync | Heavy | Data source synchronization |
| add_companies_by_market_cap | Heavy | Add top N companies by market cap |
| packet_build | Light | Rebuild packets without re-ingesting |
| echo | Light | Test/dummy job |

### 8.2 Concurrency

- **Heavy commands**: Subject to global concurrency limit (default: 4 concurrent)
- **Light commands**: Run immediately, bypass the heavy queue

### 8.3 Per-user limit

One job per user at a time. If a user has a job with status `running` or `queued`, new jobs are rejected (HTTP 409).

### 8.4 Plan gating

**Free plan monthly limits:**

| Command | Monthly limit |
|---|---|
| country_refresh | 5 |
| industry_refresh | 5 |
| company_refresh | 5 |
| universe_refresh | 2 |
| backfill | 2 |
| data_sync | 5 |
| add_companies_by_market_cap | 3 |

Counts completed jobs in the current calendar month. Rejects with HTTP 402 if exceeded.

**Pro plan**: Unlimited jobs (subject to global concurrency).

**Admin role**: Bypasses all plan limits (effective plan = "pro").

### 8.5 Job lifecycle

```
queued → running → done | failed | cancelled
```

On server restart, all `running` and `queued` jobs are marked `failed` (no resumption).

### 8.6 Log streaming

Jobs stream logs live via SSE polling. If the job is finished, all stored log lines are replayed. If running, stored lines are replayed then live lines are streamed with 5-second keepalive pings.

---

## 9. Data freshness

Each data source has a freshness window. Data is re-fetched only if the last fetch exceeds the window.

| Source | Freshness window |
|---|---|
| world_bank | 30 days |
| imf_weo | 30 days |
| fred | 1 day |
| yfinance_market | 4 hours |
| gdelt | 7 days |
| sec_edgar | 30 days |
| yfinance_fundamentals | 30 days |

**Staleness check**: `age_hours = (now - fetched_at) / 3600; stale = age_hours > threshold`

Sources not in the freshness table are always re-fetched.

---

## 10. Evidence discipline

### 10.1 Rules

- All raw fetches are stored as artefacts with source metadata, fetch timestamp, content hash, and storage URI
- All normalised data points reference an `artefact_id`
- All scores reference the exact data points used (via `point_ids`)
- All packets reference `score_ids` for version control

### 10.2 Prohibitions

No endpoint may emit:
- Unstored facts
- Invented narrative explanations
- Numeric values not derivable from stored inputs

### 10.3 Artefact uniqueness

One artefact per unique `(data_source_id, content_hash)` pair. Duplicate fetches with identical content are deduplicated.

---

## 11. Authentication and billing

### 11.1 Auth

- **Provider**: Google OAuth (OIDC)
- **Token**: JWT stored as httpOnly cookie (`access_token`)
- **Roles**: `user` (default), `admin`
- **Plans**: `free` (default), `pro`
- Admin role overrides plan to `pro`

### 11.2 Stripe billing

- Checkout session creates Stripe subscription
- Webhook updates subscription status in DB
- Portal session for self-service management
- Subscription model tracks `stripe_customer_id`, `stripe_subscription_id`, `plan`, `status`, `current_period_end`

---

## 12. Version history

| Version | Date | Change |
|---|---|---|
| company_v1 | — | Initial company scoring |
| company_v2 | — | Absolute scoring with industry context (50/30/20 weights) |
| company_v3 | 2026-03-01 | Remove industry context double-counting (60/40 weights) |
| recommendation_v1 | — | Initial composite scoring (20/20/60 thresholds 70/40) |
| recommendation_v2 | 2026-03-01 | Version bump for new company formula (thresholds unchanged) |
| country_v2 | — | Absolute scoring (50/40/10 weights) |
| industry_v3 | — | Continuous absolute scoring (replaced binary rubric) |
