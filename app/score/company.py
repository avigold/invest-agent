"""Deterministic company scoring engine — fundamentals + market."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Callable

from collections import defaultdict

from sqlalchemy import select, desc, func, literal_column, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Company,
    CompanyPriceHistory,
    CompanyRiskRegister,
    CompanyScore,
    CompanySeries,
    CompanySeriesPoint,
)
from app.score.absolute import absolute_score
from app.score.country import (
    compute_1y_return,
    compute_max_drawdown,
    compute_ma_spread,
)
from app.score.versions import (
    COMPANY_CALC_VERSION,
    COMPANY_WEIGHTS,
    COMPANY_WEIGHTS_NO_FUNDAMENTALS,
    FUNDAMENTAL_ABSOLUTE_THRESHOLDS,
    FUNDAMENTAL_INDICATORS,
    MARKET_ABSOLUTE_THRESHOLDS,
)

# Fundamental metrics that need two years of data for growth calculations
_GROWTH_METRICS = {"revenue", "net_income", "eps_diluted"}


async def _load_latest_fundamentals(
    db: AsyncSession,
    companies: list[Company],
) -> dict[str, dict[str, list[float]]]:
    """Load the 2 most recent annual values per fundamental metric per company.

    Uses a single batch query with ROW_NUMBER() window function instead of
    one query per company.

    Returns {ticker: {series_name: [latest_val, prior_val]}}.
    """
    if not companies:
        return {}

    company_ids = [c.id for c in companies]
    ticker_map = {c.id: c.ticker for c in companies}
    result: dict[str, dict[str, list[float]]] = {c.ticker: {} for c in companies}

    # Window function: rank points within each (company, series) by date desc
    rn = func.row_number().over(
        partition_by=[CompanySeries.company_id, CompanySeries.series_name],
        order_by=CompanySeriesPoint.date.desc(),
    ).label("rn")

    subq = (
        select(
            CompanySeries.company_id,
            CompanySeries.series_name,
            CompanySeriesPoint.value,
            rn,
        )
        .join(CompanySeries)
        .where(
            CompanySeries.company_id.in_(company_ids),
            CompanySeries.source.in_(["sec_edgar", "yfinance", "fmp"]),
        )
        .subquery()
    )

    query = select(subq).where(subq.c.rn <= 2).order_by(
        subq.c.company_id, subq.c.series_name, subq.c.rn,
    )
    rows = await db.execute(query)

    for row in rows.all():
        ticker = ticker_map.get(row.company_id)
        if ticker:
            result[ticker].setdefault(row.series_name, []).append(float(row.value))

    return result


def _compute_derived_ratios(
    fundamentals: dict[str, dict[str, list[float]]],
) -> dict[str, dict[str, float | None]]:
    """Compute financial ratios from raw EDGAR values.

    Returns {ticker: {ratio_name: value}}.
    """
    result: dict[str, dict[str, float | None]] = {}

    for ticker, metrics in fundamentals.items():
        ratios: dict[str, float | None] = {}

        latest_ni = metrics.get("net_income", [None])[0]
        latest_equity = metrics.get("stockholders_equity", [None])[0]
        latest_revenue = metrics.get("revenue", [None])[0]
        latest_liabilities = metrics.get("total_liabilities", [None])[0]
        latest_cash_ops = metrics.get("cash_from_ops", [None])[0]
        latest_capex = metrics.get("capex", [None])[0]

        # ROE
        if latest_ni is not None and latest_equity is not None and latest_equity != 0:
            ratios["roe"] = latest_ni / latest_equity
        else:
            ratios["roe"] = None

        # Net margin
        if latest_ni is not None and latest_revenue is not None and latest_revenue != 0:
            ratios["net_margin"] = latest_ni / latest_revenue
        else:
            ratios["net_margin"] = None

        # Debt/equity
        if latest_liabilities is not None and latest_equity is not None and latest_equity != 0:
            ratios["debt_equity"] = latest_liabilities / latest_equity
        else:
            ratios["debt_equity"] = None

        # Revenue growth (YoY)
        rev = metrics.get("revenue", [])
        if len(rev) >= 2 and rev[1] != 0:
            ratios["revenue_growth"] = (rev[0] - rev[1]) / abs(rev[1])
        else:
            ratios["revenue_growth"] = None

        # EPS growth (YoY)
        eps = metrics.get("eps_diluted", [])
        if len(eps) >= 2 and eps[1] != 0:
            ratios["eps_growth"] = (eps[0] - eps[1]) / abs(eps[1])
        else:
            ratios["eps_growth"] = None

        # FCF yield = (cash_from_ops - capex) / revenue
        if (
            latest_cash_ops is not None
            and latest_capex is not None
            and latest_revenue is not None
            and latest_revenue != 0
        ):
            fcf = latest_cash_ops - latest_capex
            ratios["fcf_yield"] = fcf / latest_revenue
        else:
            ratios["fcf_yield"] = None

        result[ticker] = ratios

    return result


def _compute_fundamental_subscores(
    derived_ratios: dict[str, dict[str, float | None]],
) -> dict[str, float]:
    """Score each fundamental ratio via absolute_score(), average to 0-100.

    Universe-independent: each company scored on its own merits.
    Returns {ticker: fundamental_subscore}.
    """
    tickers = sorted(derived_ratios.keys())
    if not tickers:
        return {}

    scores: dict[str, float] = {}
    for ticker in tickers:
        indicator_scores: list[float] = []
        for indicator in FUNDAMENTAL_INDICATORS:
            value = derived_ratios[ticker].get(indicator)
            th = FUNDAMENTAL_ABSOLUTE_THRESHOLDS[indicator]
            s = absolute_score(value, th["floor"], th["ceiling"], th["higher_is_better"])
            indicator_scores.append(s)
        scores[ticker] = round(sum(indicator_scores) / len(indicator_scores), 2)

    return scores


async def _load_equity_prices(
    db: AsyncSession,
    companies: list[Company],
    tail: int = 0,
) -> dict[str, list[dict]]:
    """Load daily close prices from CompanyPriceHistory (JSONB).

    When tail > 0, only the last `tail` entries are returned (for scoring).
    When tail == 0, the full history is returned (for charting).

    Falls back to CompanySeries/CompanySeriesPoint for legacy data.
    Returns {ticker: [{"date": ..., "close": ...}]}.
    """
    result: dict[str, list[dict]] = {}
    company_ids = [c.id for c in companies]
    ticker_map = {c.id: c.ticker for c in companies}

    # Batch-load price histories
    if company_ids:
        rows = await db.execute(
            select(
                CompanyPriceHistory.company_id,
                CompanyPriceHistory.prices,
            ).where(
                CompanyPriceHistory.company_id.in_(company_ids)
            )
        )
        for row in rows.all():
            ticker = ticker_map.get(row[0])
            if not ticker:
                continue
            raw_prices = row[1] or []
            if tail > 0 and len(raw_prices) > tail:
                raw_prices = raw_prices[-tail:]
            prices = []
            for p in raw_prices:
                price_val = p.get("price") or p.get("close")
                if price_val is not None:
                    prices.append({"date": p["date"], "close": float(price_val)})
            result[ticker] = prices

    # Fill in any companies without JSONB data from legacy series
    missing = [c for c in companies if c.ticker not in result]
    for company in missing:
        query = (
            select(CompanySeriesPoint.date, CompanySeriesPoint.value)
            .join(CompanySeries)
            .where(
                CompanySeries.company_id == company.id,
                CompanySeries.series_name == "equity_close",
            )
            .order_by(CompanySeriesPoint.date)
        )
        rows = await db.execute(query)
        prices = [{"date": str(r.date), "close": float(r.value)} for r in rows.all()]
        result[company.ticker] = prices

    return result


async def _load_point_ids_batch(
    db: AsyncSession,
    companies: list[Company],
) -> dict[str, list[str]]:
    """Batch-load series point IDs used in scoring for evidence lineage.

    Only loads the 2 most recent points per fundamental series (matching what
    _load_latest_fundamentals actually uses), not every historical point.

    Returns {ticker: [point_id_str, ...]}.
    """
    if not companies:
        return {}

    company_ids = [c.id for c in companies]
    ticker_map = {c.id: c.ticker for c in companies}
    result: dict[str, list[str]] = defaultdict(list)

    # Use same window function to get only the 2 most recent per series
    rn = func.row_number().over(
        partition_by=[CompanySeries.company_id, CompanySeries.series_name],
        order_by=CompanySeriesPoint.date.desc(),
    ).label("rn")

    subq = (
        select(
            CompanySeries.company_id,
            CompanySeriesPoint.id.label("point_id"),
            rn,
        )
        .join(CompanySeries)
        .where(
            CompanySeries.company_id.in_(company_ids),
            CompanySeries.source.in_(["sec_edgar", "yfinance", "fmp"]),
        )
        .subquery()
    )

    query = select(subq.c.company_id, subq.c.point_id).where(subq.c.rn <= 2)
    rows = await db.execute(query)
    for row in rows.all():
        ticker = ticker_map.get(row[0])
        if ticker:
            result[ticker].append(str(row[1]))

    return dict(result)


async def compute_company_scores(
    db: AsyncSession,
    companies: list[Company],
    as_of: date,
    log_fn: Callable[[str], None],
) -> list[CompanyScore]:
    """Compute scores for the given companies using absolute scoring."""
    log_fn(f"Computing scores for {len(companies)} companies...")

    # Load data (all batch queries)
    fundamentals = await _load_latest_fundamentals(db, companies)
    derived_ratios = _compute_derived_ratios(fundamentals)
    prices_data = await _load_equity_prices(db, companies, tail=400)
    all_point_ids = await _load_point_ids_batch(db, companies)

    # Fundamental sub-scores
    fundamental_subscores = _compute_fundamental_subscores(derived_ratios)

    # Market sub-scores via absolute scoring
    tickers = sorted(c.ticker for c in companies)
    market_metrics: dict[str, dict[str, float | None]] = {}
    for ticker in tickers:
        prices = prices_data.get(ticker, [])
        market_metrics[ticker] = {
            "return_1y": compute_1y_return(prices),
            "max_drawdown": compute_max_drawdown(prices),
            "ma_spread": compute_ma_spread(prices),
        }

    market_subscores: dict[str, float] = {}
    for ticker in tickers:
        metric_scores: list[float] = []
        for name, value in market_metrics[ticker].items():
            th = MARKET_ABSOLUTE_THRESHOLDS[name]
            s = absolute_score(value, th["floor"], th["ceiling"], th["higher_is_better"])
            metric_scores.append(s)
        market_subscores[ticker] = round(sum(metric_scores) / len(metric_scores), 2)

    # Combine with weights (reweight when fundamentals are missing)
    scores: list[CompanyScore] = []

    for company in companies:
        t = company.ticker
        fund = fundamental_subscores.get(t, 50.0)
        mkt = market_subscores.get(t, 50.0)

        # Detect if this company has no fundamental data
        has_fundamentals = bool(fundamentals.get(t))
        w = COMPANY_WEIGHTS if has_fundamentals else COMPANY_WEIGHTS_NO_FUNDAMENTALS

        overall = fund * w["fundamental"] + mkt * w["market"]
        overall = round(overall, 2)

        point_ids = all_point_ids.get(t, [])

        component_data = {
            "fundamental_ratios": derived_ratios.get(t, {}),
            "market_metrics": market_metrics.get(t, {}),
        }

        score = CompanyScore(
            company_id=company.id,
            as_of=as_of,
            calc_version=COMPANY_CALC_VERSION,
            fundamental_score=Decimal(str(fund)),
            market_score=Decimal(str(mkt)),
            industry_context_score=Decimal("0"),
            overall_score=Decimal(str(overall)),
            component_data=component_data,
            point_ids=point_ids,
        )
        scores.append(score)

        log_fn(f"  {t}: overall={overall:.1f} (fund={fund:.1f}, mkt={mkt:.1f})")

    return scores


def detect_company_risks(
    db: AsyncSession | None,
    company: Company,
    score: CompanyScore,
    as_of: date,
    log_fn: Callable[[str], None],
) -> list[CompanyRiskRegister]:
    """Threshold-based risk detection from stored score data."""
    risks: list[CompanyRiskRegister] = []
    cd = score.component_data or {}
    ratios = cd.get("fundamental_ratios", {})
    market = cd.get("market_metrics", {})

    # High debt
    de = ratios.get("debt_equity")
    if de is not None and de > 3.0:
        risks.append(CompanyRiskRegister(
            company_id=company.id,
            risk_type="high_debt",
            severity="high",
            description=f"Debt/equity ratio of {de:.1f} exceeds threshold of 3.0",
            detected_at=as_of,
        ))

    # Low margin (negative)
    margin = ratios.get("net_margin")
    if margin is not None and margin < 0:
        risks.append(CompanyRiskRegister(
            company_id=company.id,
            risk_type="low_margin",
            severity="medium",
            description=f"Net margin of {margin:.1%} is negative",
            detected_at=as_of,
        ))

    # Revenue decline
    rev_growth = ratios.get("revenue_growth")
    if rev_growth is not None and rev_growth < -0.10:
        risks.append(CompanyRiskRegister(
            company_id=company.id,
            risk_type="revenue_decline",
            severity="high",
            description=f"Revenue declined {rev_growth:.1%} year-over-year",
            detected_at=as_of,
        ))

    # Market drawdown
    dd = market.get("max_drawdown")
    if dd is not None and dd < -0.30:
        risks.append(CompanyRiskRegister(
            company_id=company.id,
            risk_type="market_drawdown",
            severity="medium",
            description=f"Max drawdown of {dd:.1%} in trailing 12 months",
            detected_at=as_of,
        ))

    # Low overall score
    if float(score.overall_score) < 30:
        risks.append(CompanyRiskRegister(
            company_id=company.id,
            risk_type="low_score",
            severity="high",
            description=f"Overall score of {float(score.overall_score):.1f} is below 30",
            detected_at=as_of,
        ))

    if risks:
        log_fn(f"  {company.ticker}: {len(risks)} risk(s) detected")

    return risks
