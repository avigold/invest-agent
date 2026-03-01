# PRD 5.5 — Interactive Stock Chart on Company Detail Pages

**Product**: investagent.app
**Version**: 5.5 (incremental, builds on PRD 5.4)
**Date**: 2026-03-01
**Status**: In Progress
**Milestone**: 5

---

## 1. What this PRD covers

Add an interactive stock price chart to each company detail page, showing historical close prices with period selection, market open/closed status, and responsive mobile behavior.

## 2. Problem statement

Company detail pages show scores, ratios, and evidence but lack any visual price history. Users cannot see price trends, correlations with score changes, or whether the market is currently open. This forces users to check external tools for basic price context.

## 3. Solution overview

### 3.1 New API endpoint

`GET /v1/company/{ticker}/chart?period=1w|1m|3m|6m|1y|5y`

Returns historical daily close prices from the existing `CompanySeriesPoint` table, plus a `latest` block with daily change and a `market_status` block.

Response shape:
```json
{
  "ticker": "AAPL",
  "currency": "USD",
  "period": "1y",
  "points": [
    { "date": "2025-03-01", "value": 175.23 }
  ],
  "latest": {
    "date": "2026-02-28",
    "value": 198.50,
    "change_1d": 2.30,
    "change_1d_pct": 0.0117,
    "prev_close": 196.20
  },
  "market_status": {
    "is_open": false,
    "exchange": "NYSE",
    "next_open": "2026-03-02T14:30:00Z",
    "last_close_time": "2026-02-28T21:00:00Z"
  }
}
```

### 3.2 Market status utility

Server-side detection of exchange trading hours:
- NYSE: Mon-Fri 9:30-16:00 ET
- Extensible to other exchanges via country_iso2 mapping
- No holiday calendar for MVP (documented limitation)

### 3.3 Frontend chart

Built with TradingView Lightweight Charts (WebGL-accelerated, financial-grade):
- Area chart with brand blue gradient fill
- Period selector: 1W, 1M, 3M, 6M, 1Y, 5Y
- Crosshair hover updates price display
- Pulsing green dot when market is open
- 400px height on desktop, 280px on mobile
- Touch pan/zoom on mobile (built into library)
- Polls every 60s when market is open

## 4. Data constraints

The database stores daily close prices only (from yfinance batch ingestion). No intraday data is available. When the market is open, the chart shows the last recorded daily close. The market status indicator provides context about whether new data may be forthcoming.

## 5. Files changed

| File | Action |
|---|---|
| `app/utils/market_hours.py` | New — exchange schedule + market status |
| `app/api/routes_companies.py` | Modify — add chart endpoint |
| `tests/test_company_chart.py` | New — backend tests |
| `web/package.json` | Modify — add lightweight-charts |
| `web/src/components/MarketStatus.tsx` | New — market open/closed badge |
| `web/src/components/PriceHeader.tsx` | New — price + change display |
| `web/src/components/StockChart.tsx` | New — chart + period selector + polling |
| `web/src/pages/CompanyDetail.tsx` | Modify — integrate StockChart |

## 6. Acceptance criteria

- [ ] `GET /v1/company/{ticker}/chart?period=1y` returns historical price data
- [ ] Invalid period returns 400
- [ ] Unknown ticker returns 404
- [ ] Market status correctly reflects NYSE hours
- [ ] Chart renders on company detail page with area gradient
- [ ] Period selector switches between 1W/1M/3M/6M/1Y/5Y
- [ ] Crosshair hover updates price header display
- [ ] Market open: pulsing green dot, 60s polling
- [ ] Market closed: static gray dot, no polling
- [ ] Chart resizes responsively (400px desktop, 280px mobile)
- [ ] All existing tests continue to pass

## 7. Known limitations

- **KI-1**: No US market holiday calendar — market status shows "open" on holidays but no new data appears
- **KI-2**: No intraday data — chart shows daily close prices only
- **KI-3**: Only NYSE schedule implemented — other exchanges use NYSE as fallback
