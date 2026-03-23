# Feature Roadmap — Bloomberg/YCharts Parity

Goal: Make Invest Agent a less-expensive alternative to a Bloomberg terminal or YCharts account.

## Quick Wins (High Priority, Small Effort)

| # | Feature | Status | PRD |
|---|---------|--------|-----|
| 1 | **Watchlist** — User-curated ticker list with live prices | Done | PRD 10.0 |
| 2 | **CSV/Excel export** — Download any table as CSV/XLSX | Done | PRD 10.1 |
| 3 | **Volume on chart** — Volume bars under price chart (lightweight-charts supports natively) | Done | PRD 10.2 |
| 4 | **Benchmark comparison** — Stock performance vs S&P 500 / sector ETF | Done | PRD 10.2 |
| 5 | **Key ratio dashboard** — Clean card layout of P/E, P/B, ROE, margins | Not Started | |
| 6 | **Saved screener configs** — Persist and reuse screener filters | Not Started | |
| 7 | **Recommendation change alerts** — Surface when Buy/Hold/Sell flips | Not Started | |

## Medium Effort, High Value

| # | Feature | Status | PRD |
|---|---------|--------|-----|
| 8 | **Peer/comparable analysis** — Side-by-side metric comparison of 2-5 companies | Not Started | |
| 9 | **Multi-ticker chart overlay** — Compare price histories on one chart | Not Started | |
| 10 | **Relative valuation** — Company multiples vs sector/industry medians | Not Started | |
| 11 | **Portfolio tracker** — Log holdings, cost basis, P&L, allocation breakdown | Not Started | |
| 12 | **Financial statements** — Full income/balance/cashflow display (quarterly + annual) | Not Started | |
| 13 | **Company news feed** — Aggregated headlines per ticker (RSS, free APIs) | Not Started | |
| 14 | **Score change alerts** — Track meaningful score movements between refreshes | Not Started | |

## Bigger Lifts

| # | Feature | Status | PRD |
|---|---------|--------|-----|
| 15 | **Portfolio performance chart** — Time-weighted return vs benchmarks | Not Started | |
| 16 | **Technical indicators** — SMA, EMA, Bollinger, RSI, MACD overlays | Not Started | |
| 17 | **Economic calendar** — Upcoming data releases with consensus expectations | Not Started | |
| 18 | **DCF / intrinsic value** — Adjustable discount model | Not Started | |
| 19 | **AI research chat** — Natural language Q&A over your data | Not Started | |
| 20 | **PDF report generation** — Formatted research reports for a company | Not Started | |

## Existing Differentiators (Keep and Strengthen)

- **ML stock picking** — trainable LightGBM models with 186 features
- **Multi-layer composite scoring** — transparent country + industry + company weights
- **Evidence discipline** — all scores trace to stored artefacts with lineage
- **Dual scoring systems** — deterministic + ML provide complementary signals
- **Job pipeline visibility** — SSE log streaming for data pipelines
