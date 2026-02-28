# PRD 1.0 — Invest Agent

**Product**: investagent.app
**Version**: 1.0
**Date**: 2026-02-28
**Status**: Draft

---

## 1. Vision

Invest Agent is an automated investment research platform for solo investors. It ingests macro, industry, and company data from public sources, computes deterministic scores, and produces evidence-backed decision packets — replacing manual spreadsheet-driven research workflows.

The system runs research as background jobs, streams progress in real time, and surfaces results through a rich dashboard with charts, statistics, and drill-down evidence views.

## 2. Target user

**Solo retail investor** who wants systematic, data-driven country/industry/company research without building their own data pipeline or maintaining spreadsheets.

Key traits:
- Makes allocation decisions across countries, industries, and individual equities
- Values transparency: wants to see the data behind every score
- Comfortable with a dashboard UI but not writing code
- Runs research periodically (daily/weekly refresh cycles)

## 3. Product principles

1. **Deterministic and reproducible** — Every score is pinned to a `calc_version`. Re-running the same inputs produces the same output.
2. **Evidence-first** — No score or summary exists without stored, traceable source data. No hallucinated narratives.
3. **Jobs, not magic** — Every compute action is a visible job with status, logs, and artefacts. Users see what's running and what failed.
4. **Simple over clever** — Explicit code paths, flat data models, minimal abstraction layers.

## 4. Tech stack

### Backend
| Component | Choice |
|-----------|--------|
| Language | Python 3.11+ |
| Web framework | FastAPI |
| Database | PostgreSQL |
| Migrations | Alembic |
| HTTP client | httpx |
| Background jobs | In-process worker pool (MVP); Redis + RQ/Celery if needed |
| Streaming logs | SSE endpoint per job |
| CLI | Typer |

### Frontend
| Component | Choice |
|-----------|--------|
| Framework | Next.js (React) + TypeScript |
| Styling | Tailwind CSS |
| Theme | Dark mode (similar to mysecond.app) |
| Charts | Recharts or D3 (TBD) |
| Auth flow | Google OAuth (OIDC) |

### Infrastructure
| Component | Choice |
|-----------|--------|
| Dev | Docker Compose |
| Prod | systemd + gunicorn/uvicorn behind nginx |
| Artefact storage | Local filesystem (dev); S3-compatible (prod) |
| Billing | Stripe (Free / Pro tiers) |

## 5. Plans and billing

| | Free | Pro |
|---|---|---|
| Price | $0 | TBD/month |
| Jobs per month | Limited quota per command | Unlimited (global concurrency cap) |
| Data refresh | Manual only | Daily auto-refresh |
| Decision packets | View only | View + export |
| Country universe | Top 10 | Full supported list |

Admin/titled roles may bypass limits (mirrors `_effective_plan()` pattern from mysecond.app).

## 6. Information architecture

### Data layers

```
Country (macro)
  └─ World Bank indicators, FRED rates, GDELT stability, equity index proxy
      └─ Country series → Country scores → Country decision packets

Industry (sector)
  └─ Template-driven rubrics + macro regime inputs from country layer
      └─ Industry scores → Industry decision packets

Company (micro)
  └─ SEC EDGAR filings + XBRL facts, EOD market data
      └─ Company scores → Company decision packets
```

Each layer feeds into the next. Country macro conditions inform industry scoring; industry context informs company evaluation.

### Evidence chain

```
Raw fetch → Artefact (content-hashed, stored) → Normalised data point → Score input → Score → Decision packet
```

Every link in this chain is persisted and queryable. The `include_evidence=true` flag on any endpoint returns the full lineage.

## 7. Feature set by milestone

### Milestone 1 — Foundation (Target: this week)

**Auth and users**
- Google OAuth (OIDC) login flow
- User model with profile basics
- Session management (JWT or session cookie — TBD)

**Subscriptions**
- Stripe customer creation on signup
- Free/Pro plan gating
- Plan-aware middleware for API routes

**Job system**
- `jobs` table with status lifecycle: `queued → running → done | failed | cancelled`
- Global concurrency limiter for heavy jobs
- Per-user concurrency limits
- Light job bypass for fast operations
- SSE endpoint for live log streaming (`GET /api/jobs/{id}/stream`)
- On restart: mark any `running` jobs as `cancelled`
- Job params validated via Pydantic schemas

**API skeleton**
- `GET /healthz`
- `POST /api/jobs` (enqueue, plan-gated)
- `GET /api/jobs/{id}` (status + metadata)
- `GET /api/jobs/{id}/stream` (SSE logs)

**Frontend skeleton**
- Next.js project setup with Tailwind dark theme
- Google OAuth login page
- Dashboard shell with navigation
- Jobs list view with status indicators (blue=running, green=done, red=failed)
- Job detail view with live log stream

**Infra**
- Docker Compose for local dev (Postgres, backend, frontend)
- Alembic migration setup
- Basic CI (lint + test)

**Deliverables**: Auth flow works end-to-end. User can log in, enqueue a dummy job, watch it stream logs, and see it complete.

---

### Milestone 2 — Country Module v1

**Data ingestion**
- World Bank Indicators API client (GDP, inflation, reserves, current account, etc.)
- FRED client (rates, credit spreads where applicable)
- GDELT stability index pipeline (monthly, deterministic transform)
- Equity index proxy returns/drawdown (config-mapped symbol per country)

**Artefact storage**
- `artefacts` table: source metadata, fetch time window, content hash, storage URI
- `data_sources` registry
- All normalised data points reference their source `artefact_id`

**Scoring**
- `country_series` + `country_series_points` tables
- Scoring engine with pinned `calc_version`
- Category scores: macro strength, stability, market performance, risk
- Composite country score (weighted, deterministic)
- `country_scores` table with full input references
- `country_risk_register` for flagged risks

**Decision packets**
- `decision_packets` table
- Country packet builder with pinned `summary_version`
- Assembled strictly from stored facts — no invented narrative
- Packets include: score breakdown, key indicators, trend data, risk flags

**API**
- `GET /v1/countries` — latest scores for all countries in universe
- `GET /v1/country/{iso2}/summary?as_of=YYYY-MM-01&include_evidence=true|false`

**Frontend**
- Country ranking dashboard with sortable table
- Country detail page: score card, indicator charts, trend lines, risk flags
- Evidence drill-down view (toggled via `include_evidence`)
- Time-series charts for key indicators

**Job commands**
- `country_refresh` — ingest + score + build packet for one or all countries

**Config**
- `investable_countries_v1.json` — the initial country list (provided by user)

**Deliverables**: User can trigger `country_refresh`, see it ingest live data, compute scores, and view the resulting country dashboard with charts and evidence.

---

### Milestone 3 — Industry Module v1

**Scoring**
- Template-driven rubric system (configurable per industry)
- Macro regime inputs derived from country layer
- Industry score with `calc_version` pinning

**Decision packets**
- Industry packets assembled from stored rubric evaluations
- Cross-references country macro context

**API**
- `GET /v1/industries` — scored industry list
- `GET /v1/industry/{id}/summary?include_evidence=true|false`

**Frontend**
- Industry scoring dashboard
- Rubric breakdown view
- Macro regime context panel

**Job commands**
- `industry_refresh`

**Deliverables**: User can score industries against template rubrics informed by country macro data.

---

### Milestone 4 — Company Module v1

**Data ingestion**
- SEC EDGAR API client + XBRL facts extraction (US companies first)
- EOD market data provider (swappable adapter)
- OpenFIGI identifier mapping (optional)

**Scoring**
- Company scoring engine with `calc_version` pinning
- Financial metrics from filings (revenue, margins, debt ratios, etc.)
- Market metrics (returns, volatility, valuation multiples)

**Decision packets**
- Company packets with financial + market + industry context
- Evidence chain from raw filing → extracted fact → score

**API**
- `GET /v1/companies` — scored company list
- `GET /v1/company/{ticker}/summary?include_evidence=true|false`

**Job commands**
- `company_refresh` — ingest filings + market data, score, build packet
- `universe_refresh` — batch refresh for user's watchlist
- `backfill` — historical filings/series backfill
- `packet_build` — rebuild packets without re-ingesting

**Frontend**
- Company dashboard with watchlist
- Company detail: financials, charts, score breakdown, filing evidence
- Comparison views

**Deliverables**: User can research US public companies with SEC filing data and market data, view scores with full evidence lineage.

## 8. Database schema (core tables)

```
users
  id, email, name, google_id, plan, created_at

subscriptions
  id, user_id, stripe_customer_id, stripe_subscription_id, plan, status, current_period_end

jobs
  id, user_id, command, params (jsonb), status, queued_at, started_at, finished_at, log_text, artefact_ids, packet_id

data_sources
  id, name, base_url, description

artefacts
  id, data_source_id, fetch_params (jsonb), fetched_at, time_window_start, time_window_end, content_hash, storage_uri, size_bytes

countries
  id, iso2, iso3, name, region, investable (bool)

country_series
  id, country_id, indicator_code, data_source_id, unit, frequency

country_series_points
  id, series_id, date, value, artefact_id

country_scores
  id, country_id, calc_version, scored_at, category_scores (jsonb), composite_score, input_point_ids (jsonb)

country_risk_register
  id, country_id, risk_type, severity, description, artefact_id, detected_at

decision_packets
  id, entity_type, entity_id, summary_version, calc_version, built_at, content (jsonb), input_score_ids (jsonb)
```

Industry and company tables follow the same pattern and are added in Milestones 3 and 4.

## 9. API endpoints (full list)

| Method | Path | Auth | Milestone |
|--------|------|------|-----------|
| GET | `/healthz` | No | 1 |
| POST | `/api/jobs` | Yes, plan-gated | 1 |
| GET | `/api/jobs/{id}` | Yes, owner | 1 |
| GET | `/api/jobs/{id}/stream` | Yes, owner | 1 |
| GET | `/v1/countries` | Yes | 2 |
| GET | `/v1/country/{iso2}/summary` | Yes | 2 |
| GET | `/v1/industries` | Yes | 3 |
| GET | `/v1/industry/{id}/summary` | Yes | 3 |
| GET | `/v1/companies` | Yes | 4 |
| GET | `/v1/company/{ticker}/summary` | Yes | 4 |
| POST | `/v1/admin/refresh` | Admin | 2 |

## 10. Scoring display

Scores are presented as **score + evidence**:
- Composite score (numeric) with category breakdown
- Supporting data points shown alongside each category
- Trend indicators (improving/declining/stable)
- Charts for time-series indicators
- Risk flags highlighted

Internal weights are not exposed to the user. The focus is on "here's your score, here's the data that produced it."

## 11. Scheduling

- **Shared datasets** (country, market indices): computed once globally, cached. Per-user jobs reference shared artefacts and scores.
- **User-specific** (watchlists, universes): user-tailored packets join against shared data.
- **Pro users**: daily auto-refresh via scheduler (`python -m app.cli run daily`).
- **Free users**: manual refresh only, subject to monthly quota.

## 12. Non-functional requirements

- **Idempotency**: All ingestion and job operations are safe to re-run (unique constraints + upserts).
- **Observability**: Job logs are first-class, streamable, and persisted.
- **Failure visibility**: Failed jobs show clear error context. No silent failures.
- **Data integrity**: Content-hashed artefacts. No unstored facts. No invented explanations.
- **Security**: Per-user job isolation. Users cannot access other users' jobs or data.

## 13. Out of scope for v1

- Team/multi-analyst workspaces
- Mobile app
- Real-time market data streaming
- Algorithmic trading or order execution
- Non-US company filings (post-v1 expansion)
- PDF export of decision packets
- Email/notification system
- Public API for third-party integrations

## 14. Open items

- [ ] Charting library decision: Recharts vs D3 vs alternative
- [ ] Session management: JWT vs httpOnly session cookie
- [ ] Investable countries list (user to provide)
- [ ] Exact Free tier monthly quotas
- [ ] Pro tier pricing
- [x] GDELT stability index transform specification — resolved in PRD 2.0 (DOC 2.0 API, theme-based instability volume)
- [x] EOD market data provider selection — yfinance for MVP
