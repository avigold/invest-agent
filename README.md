# Invest Agent

A multi-tenant investment research platform that combines deterministic fundamentals-based scoring with ML-driven stock picking. Designed as a less-expensive alternative to Bloomberg Terminal and YCharts, Invest Agent ingests data from 8+ sources, scores companies across 10 countries and 11 GICS sectors, and surfaces actionable Buy/Hold/Sell signals through an interactive web interface.

## Table of Contents

- [Core Capabilities](#core-capabilities)
- [Scoring Systems](#scoring-systems)
- [Data Sources](#data-sources)
- [Feature Set](#feature-set)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [CLI Commands](#cli-commands)
- [Automated Scheduler](#automated-scheduler)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Project Structure](#project-structure)

---

## Core Capabilities

- **Multi-layer scoring**: Country, industry, and company scores compose into Buy/Hold/Sell recommendations with full evidence lineage
- **Dual scoring systems**: A deterministic fundamentals-based scorer (22 features) and an ML/LightGBM predictor (186 features) operate independently and provide complementary signals
- **Evidence discipline**: Every score traces back to stored artefacts with source metadata, fetch timestamps, and content hashes — no unstored facts or invented narratives
- **Live job pipeline**: Background jobs stream logs in real time via SSE; users see exactly what the system is doing
- **Interactive charting**: Lightweight-charts-powered stock charts with benchmark overlays, multi-ticker comparison, and volume histograms
- **Sector-aware valuation**: Each GICS sector gets its own curated set of valuation multiples with percentile rankings against peers

---

## Scoring Systems

### Deterministic System

Fundamentals-based scoring from the CompanyScore database using 22 features. Scores are computed via absolute thresholds and normalised to 0-100. The composite recommendation blends country (20%), industry (20%), and company (60%) scores.

- **Scoring files**: `app/score/company.py`, `app/score/recommendations.py`, `app/predict/scorer.py`, `app/predict/strategy.py`, `app/predict/features.py`
- **Data source**: Database (`CompanyScore` table)
- **Portfolio construction**: Kelly criterion with sector and position constraints
- **Classification**: Buy (>70), Hold (40-70), Sell (<40)

### ML/Parquet System

LightGBM model trained on comprehensive Parquet data (186 features) via walk-forward cross-validation. The validated golden model (seed 32) achieved 84.5% average annual return across 2018-2024 backtests.

- **Scoring files**: `app/predict/parquet_scorer.py`, `app/predict/parquet_dataset.py`, `app/predict/model.py`, `app/predict/backtest.py`
- **Data source**: `data/exports/training_features.parquet` (771k rows, 199 columns, 1983-2026)
- **Portfolio construction**: Top-50 equal weight (2% each), deduplicated by company name
- **Classification**: Probability-based with Platt scaling (platt_a=-4.8195, platt_b=2.3040)

These systems are **completely independent** and must never be conflated. They provide complementary signals — when both agree on Buy, the agreement flag is surfaced in the UI.

---

## Data Sources

| Source | Data | Cadence |
|--------|------|---------|
| **World Bank Indicators** | GDP, GDP growth, inflation, unemployment, current account, FDI, reserves | Monthly |
| **IMF WEO** | Government debt as % of GDP | Monthly |
| **FRED** | Fed funds rate, high-yield spread, yield curve, credit spreads | Daily |
| **yfinance** | Equity index prices, individual stock prices, international fundamentals | Every 4 hours (prices), weekly (fundamentals) |
| **GDELT DOC 2.0** | Political instability volume, regulatory heat | Monthly |
| **SEC EDGAR** | US company filings, XBRL facts extraction, 10-K annual reports | Weekly |
| **Financial Modeling Prep** | Global fundamentals — income statement, balance sheet, cash flow | Weekly |
| **OpenFIGI** | Identifier mapping (optional, not yet integrated) | — |

---

## Feature Set

### Research & Scoring

| Feature | Description |
|---------|-------------|
| **Country Scoring** | 10 investable countries scored on macro fundamentals, market performance, and political stability |
| **Industry Scoring** | 11 GICS sectors evaluated per country using rubric-based macro sensitivity analysis |
| **Company Scoring** | Deterministic scoring on fundamental ratios and market metrics with risk registers |
| **ML Predictions** | LightGBM probability scores with contributing feature breakdowns |
| **Recommendations** | Composite Buy/Hold/Sell signals blending country, industry, and company scores |
| **Decision Packets** | Structured research outputs with full evidence chains |

### Analysis Tools

| Feature | Description |
|---------|-------------|
| **Stock Screener** | Historical screening with forward return analysis and winner profile detection |
| **Live Screener** | Real-time stock filtering with saved configurations |
| **Peer Comparison** | Side-by-side metric comparison of 2-5 companies with best/worst highlighting |
| **Multi-Ticker Chart** | Normalised percentage-return overlay of up to 5 tickers on one chart |
| **Relative Valuation** | Company multiples vs sector peer medians with dot-on-range percentile charts |
| **Key Ratio Dashboard** | P/E, P/B, ROE, margins, growth, and risk metrics in categorised cards |
| **Benchmark Comparison** | Stock performance vs country equity index overlay |

### Portfolio & Alerts

| Feature | Description |
|---------|-------------|
| **Watchlist** | User-curated ticker list with live prices and quick access |
| **Signal Change Alerts** | Tracks when Buy/Hold/Sell classifications flip across both scoring systems |
| **CSV/Excel Export** | Download any table as CSV with one click |

### Interactive Charts

| Feature | Description |
|---------|-------------|
| **Stock Chart** | Interactive price chart with period selector (1W-5Y), crosshair, and volume histogram |
| **Benchmark Overlay** | Normalised percentage comparison against country equity index |
| **Compare Chart** | Multi-ticker overlay with distinct colours, synced crosshair, and period selector |
| **Valuation vs Peers** | Horizontal dot-on-range charts showing company position within sector distribution |

### Platform

| Feature | Description |
|---------|-------------|
| **Multi-Tenant Auth** | Google OAuth (OIDC) with JWT sessions, Free/Pro plan gating |
| **Job Pipeline** | Asynchronous job execution with SSE log streaming and concurrency control |
| **Admin Dashboard** | System overview, job management, user administration |
| **Automated Scheduler** | Price sync every 4h, daily macro sync, weekly fundamentals and scoring, monthly discovery |
| **Custom Scoring Profiles** | User-configurable weight profiles for country/industry/company blend |

---

## Architecture

```
                    +-----------+       +------------+
                    |  Browser  | <---> | Vite (dev) |
                    +-----------+       +------+-----+
                                               |
                      proxy /api, /v1, /auth   |
                                               v
+----------+     +---------------------------+
| Postgres | <-> |      FastAPI Backend       |
|   16     |     |  - REST API (18 routers)  |
+----------+     |  - Job runner (threads)   |
                 |  - SSE log streaming      |
                 |  - APScheduler            |
                 +---------------------------+
                           |
              +------------+------------+
              |            |            |
         World Bank     FRED      yfinance
           IMF         GDELT     SEC EDGAR
                        FMP
```

### Backend

- **Framework**: FastAPI with async/await throughout
- **Database**: PostgreSQL 16 with SQLAlchemy 2.0 async, Alembic migrations
- **Job system**: In-process thread pool with `LiveJob` objects, per-user isolation, plan gating
- **Scheduler**: APScheduler 3.x with configurable timezone and job intervals
- **ML**: LightGBM for model training, PyArrow for Parquet data handling

### Frontend

- **Framework**: React 18 with React Router v6 (SPA with lazy-loaded routes)
- **Build**: Vite 5 with TypeScript 5
- **Data fetching**: TanStack Query v5 with stale-time caching
- **Charting**: Lightweight Charts v5.1.0 (TradingView)
- **Styling**: Tailwind CSS 3.4 (dark theme)

### Production Deployment

In production, `npm run build` outputs to `web/dist/`. The FastAPI backend serves the static files and handles SPA fallback — single process, no separate frontend server needed.

---

## Installation

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Option A: Docker Compose (Recommended)

```bash
git clone <repo-url> invest-agent
cd invest-agent
cp .env.example .env
# Edit .env with your API keys (see Configuration section)
docker compose up -d
```

This starts:
- **PostgreSQL 16** on port 5433
- **Backend** (FastAPI) on port 8000 with hot reload
- **Frontend** (Vite) on port 3000

### Option B: Local Development

#### 1. Database

```bash
# Start PostgreSQL (Docker or native)
docker run -d --name investagent-db \
  -e POSTGRES_USER=investagent \
  -e POSTGRES_PASSWORD=investagent \
  -e POSTGRES_DB=investagent \
  -p 5433:5432 \
  postgres:16
```

#### 2. Backend

```bash
cd invest-agent

# Create virtual environment and install dependencies
uv sync

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys

# Run database migrations
source .venv/bin/activate
alembic upgrade head

# Start the backend server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 3. Frontend

```bash
cd invest-agent/web

# Install dependencies
npm install

# Start dev server (proxies API calls to port 8000)
npm run dev
```

The frontend dev server runs on port 3000 and proxies `/api`, `/auth`, `/v1`, and `/healthz` to the backend on port 8000.

#### 4. Initial Data Setup

After first install, seed the system with data:

```bash
source .venv/bin/activate

# Discover and add companies (requires FMP_API_KEY)
python -m app.cli add-companies --country US --top 50
python -m app.cli add-companies --country GB --top 20

# Preload fundamentals data
python -m app.cli preload-fmp

# Sync prices
python -m app.cli sync-prices

# Score all companies
python -m app.cli score-all
```

---

## Configuration

Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
```

### Required Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL async connection string (`postgresql+asyncpg://...`) |
| `DATABASE_URL_SYNC` | PostgreSQL sync connection string (`postgresql://...`) |
| `JWT_SECRET_KEY` | Secret key for JWT session tokens (change in production) |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `APP_URL` | Frontend URL for OAuth callbacks (default: `http://localhost:3000`) |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FMP_API_KEY` | — | Financial Modeling Prep API key (required for company fundamentals) |
| `FRED_API_KEY` | — | FRED API key (US macro data; gracefully skipped if missing) |
| `STRIPE_SECRET_KEY` | — | Stripe billing (Free/Pro plans) |
| `STRIPE_PRICE_ID` | — | Stripe price ID for Pro subscription |
| `STRIPE_WEBHOOK_SECRET` | — | Stripe webhook verification |
| `MAX_CONCURRENT_HEAVY_JOBS` | `4` | Global concurrency limit for heavy jobs |
| `MAX_USER_CONCURRENT_JOBS` | `1` | Per-user concurrency limit |
| `SCHEDULER_ENABLED` | `true` | Enable/disable automated scheduler |
| `SCHEDULER_TIMEZONE` | `UTC` | Timezone for scheduled jobs |

### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create OAuth 2.0 credentials (Web application type)
3. Add `http://localhost:8000/auth/google/callback` as an authorised redirect URI
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`

---

## Running the Application

### Development

```bash
# Terminal 1: Backend
cd invest-agent
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Frontend
cd invest-agent/web
npm run dev
```

Open `http://localhost:3000` in your browser.

### Production

```bash
# Build frontend
cd invest-agent/web
npm run build

# Start backend (serves frontend static files + API)
cd invest-agent
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The backend serves `web/dist/` as static files with SPA fallback — no separate frontend process needed.

### Important Notes

- Always start the backend before the frontend dev server (Vite proxies to port 8000)
- When restarting the backend, also restart the Vite dev server — Vite's proxy holds a connection to port 8000
- On backend restart, any jobs marked `running` are automatically set to `failed`

---

## CLI Commands

All CLI commands are run from the project root with the virtual environment activated.

```bash
source .venv/bin/activate
python -m app.cli <command>
```

### Data Management

| Command | Description |
|---------|-------------|
| `add-companies --country XX --top N` | Discover and add top N companies by market cap for a country |
| `preload-fmp` | Bulk-load fundamentals from Financial Modeling Prep for all companies |
| `sync-prices` | Sync latest stock prices for all companies |
| `sync-macro` | Sync macroeconomic data (World Bank, IMF, FRED, GDELT) |
| `enrich-companies` | Enrich company metadata (sector, exchange, ADR flags) |
| `dedup-listings` | Identify and mark duplicate cross-listed tickers |

### Scoring

| Command | Description |
|---------|-------------|
| `score-all` | Re-score all companies (deterministic system) |
| `discover-companies` | Census of new companies to add |

### ML Pipeline

| Command | Description |
|---------|-------------|
| `export-training` | Export training features to Parquet |
| `train-model` | Train a new LightGBM model (walk-forward CV) |
| `score-universe` | Score all companies with the ML model |
| `evaluate-model` | Run backtest validation |

### Server

| Command | Description |
|---------|-------------|
| `serve` | Start the FastAPI server |
| `migrate` | Run Alembic database migrations |
| `run daily` | Start the automated scheduler |

---

## Automated Scheduler

When enabled (`SCHEDULER_ENABLED=true`), the following jobs run automatically:

| Schedule | Job | Description |
|----------|-----|-------------|
| Every 4 hours | `price_sync` | Update stock prices for all companies |
| 06:00 UTC daily | `macro_sync` (daily) | Sync FRED rates and market data |
| Sunday 04:00 UTC | `fmp_sync` | Refresh company fundamentals from FMP |
| Sunday 06:00 UTC | `score_sync` | Re-score stale companies, build decision packets, compute sector valuation stats |
| 1st of month 02:00 UTC | `discover_companies` | Census for new companies |
| 1st of month 03:00 UTC | `macro_sync` (monthly) | Full macro refresh (World Bank, IMF, GDELT) |
| 1st of month 07:00 UTC | `country_refresh` + `industry_refresh` | Re-score countries and industries |

---

## API Reference

All endpoints require authentication except health checks. The API is served under `/v1` (data endpoints) and `/api` (operational endpoints).

### Authentication

| Endpoint | Description |
|----------|-------------|
| `GET /auth/google/login` | Initiate Google OAuth flow |
| `GET /auth/google/callback` | OAuth callback handler |
| `GET /auth/me` | Current user info |
| `POST /auth/logout` | End session |

### Countries

| Endpoint | Description |
|----------|-------------|
| `GET /v1/countries` | List all countries with latest scores |
| `GET /v1/country/{iso2}/summary` | Country decision packet with optional evidence |

### Industries

| Endpoint | Description |
|----------|-------------|
| `GET /v1/industries` | List all industry scores by country |
| `GET /v1/industry/{gics_code}/{country_iso2}/summary` | Industry decision packet |

### Companies

| Endpoint | Description |
|----------|-------------|
| `GET /v1/companies` | List companies with scores, search, and filtering |
| `GET /v1/company/{ticker}/summary` | Company decision packet with evidence |
| `GET /v1/company/{ticker}/chart` | Historical price data for charting |
| `GET /v1/company/{ticker}/peer-valuation` | Valuation ratios vs sector peer percentiles |

### Recommendations

| Endpoint | Description |
|----------|-------------|
| `GET /api/recommendations` | Buy/Hold/Sell signals with composite scores |
| `GET /api/recommendations/{ticker}` | Detailed recommendation breakdown |

### ML Predictions

| Endpoint | Description |
|----------|-------------|
| `GET /api/predictions/scores` | ML probability scores for active model |
| `GET /api/predictions/score/{ticker}` | Detailed ML score with contributing features |
| `GET /api/predictions/models` | List trained models |
| `GET /api/predictions/models/{id}` | Model details with fold metrics |

### Signals

| Endpoint | Description |
|----------|-------------|
| `GET /v1/signals/changes` | Recent classification change alerts |

### Watchlist

| Endpoint | Description |
|----------|-------------|
| `GET /api/watchlist` | User's watchlist with live prices |
| `POST /api/watchlist/{ticker}` | Add ticker to watchlist |
| `DELETE /api/watchlist/{ticker}` | Remove ticker from watchlist |

### Jobs

| Endpoint | Description |
|----------|-------------|
| `POST /api/jobs` | Submit a new job |
| `GET /api/jobs` | List user's jobs |
| `GET /api/jobs/{id}` | Job status and result |
| `GET /api/jobs/{id}/stream` | SSE log stream |

### Screener

| Endpoint | Description |
|----------|-------------|
| `POST /api/screener/run` | Run a stock screen |
| `GET /api/screener/results` | List screen results |
| `GET /api/screener/results/{id}` | Screen result with analysis |
| `GET /api/live-screener/screen` | Real-time stock filter |

### Health

| Endpoint | Description |
|----------|-------------|
| `GET /healthz` | Health check (no auth required) |

---

## Testing

```bash
cd invest-agent
source .venv/bin/activate
python -m pytest -q
```

The test suite includes ~186 tests covering authentication, scoring logic, ML model integrity, data ingestion, API endpoints, and frontend integration.

Tests use `pytest-asyncio` with `asyncio_mode = "auto"` for async test support.

---

## Project Structure

```
invest-agent/
├── app/
│   ├── api/                    # FastAPI route handlers (18 routers)
│   │   ├── routes_companies.py # Company endpoints + peer valuation
│   │   ├── routes_predictions.py # ML prediction endpoints
│   │   ├── routes_signals.py   # Signal change alerts
│   │   └── ...
│   ├── db/
│   │   ├── models.py           # SQLAlchemy models (20+ tables)
│   │   └── session.py          # Database session management
│   ├── ingest/                 # Data source integrations
│   │   ├── fmp.py              # Financial Modeling Prep
│   │   ├── world_bank.py       # World Bank Indicators
│   │   ├── fred.py             # FRED economic data
│   │   ├── gdelt.py            # GDELT political stability
│   │   └── sec_edgar.py        # SEC EDGAR filings
│   ├── jobs/
│   │   ├── handlers/           # Job command handlers (18 handlers)
│   │   ├── registry.py         # Thread-safe job registry
│   │   ├── queue.py            # Global concurrency control
│   │   └── runner.py           # Job execution + SSE streaming
│   ├── predict/                # ML/Parquet scoring system
│   │   ├── model.py            # LightGBM training + walk-forward CV
│   │   ├── parquet_scorer.py   # Score from Parquet features
│   │   ├── parquet_dataset.py  # Training data loader
│   │   └── backtest.py         # Portfolio backtesting
│   ├── score/                  # Deterministic scoring system
│   │   ├── company.py          # Company score computation
│   │   ├── country.py          # Country score computation
│   │   ├── recommendations.py  # Buy/Hold/Sell classification
│   │   ├── sector_valuation.py # Sector percentile computation
│   │   ├── sector_metrics.py   # Sector-specific metric config
│   │   ├── signal_changes.py   # Classification change detection
│   │   └── versions.py         # Calc version constants
│   ├── scheduler/
│   │   └── daily.py            # APScheduler job definitions
│   ├── main.py                 # FastAPI app entry point
│   └── cli.py                  # Typer CLI commands
├── alembic/
│   └── versions/               # Database migrations (0001-0018)
├── config/
│   ├── investable_countries_v1.json
│   └── sector_macro_sensitivity_v1.json
├── data/
│   ├── models/                 # Trained model blobs (protected)
│   └── exports/                # Parquet datasets, backtest results
├── docs/
│   └── product/                # PRDs (prd_1_0.md through prd_10_8.md)
├── web/
│   ├── src/
│   │   ├── pages/              # React page components (22 pages)
│   │   ├── components/         # Reusable UI components
│   │   ├── lib/                # API client, auth, queries, exports
│   │   ├── App.tsx             # Router configuration
│   │   └── main.tsx            # Entry point
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── tests/                      # pytest test suite
├── scripts/                    # Utility scripts (backtesting, data export)
├── pyproject.toml              # Python project config
├── docker-compose.yml
├── Dockerfile
└── CLAUDE.md                   # AI development instructions
```

---

## Licence

This is a private project. All rights reserved.
