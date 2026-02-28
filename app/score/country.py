"""Deterministic country scoring engine."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Callable

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Country,
    CountryRiskRegister,
    CountryScore,
    CountrySeries,
    CountrySeriesPoint,
)
from app.score.versions import (
    COUNTRY_CALC_VERSION,
    COUNTRY_WEIGHTS,
    MACRO_INDICATORS,
)


def percentile_rank(values: list[float | None], higher_is_better: bool = True) -> list[float]:
    """Return 0-1 percentile ranks for a list of values.

    None values get median rank (0.5).
    Ties receive average rank.
    """
    n = len(values)
    if n == 0:
        return []

    # Build (value, original_index) pairs, separating Nones
    indexed = []
    none_indices = []
    for i, v in enumerate(values):
        if v is None:
            none_indices.append(i)
        else:
            indexed.append((v, i))

    result = [0.5] * n  # default for Nones

    if not indexed:
        return result

    # Sort: ascending if higher_is_better, descending if lower_is_better
    indexed.sort(key=lambda x: x[0], reverse=not higher_is_better)

    # Assign ranks with tie handling (average rank)
    rank = 1
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][0] == indexed[i][0]:
            j += 1
        # All items from i to j-1 share this value
        avg_rank = (rank + rank + j - i - 1) / 2.0
        for k in range(i, j):
            _, orig_idx = indexed[k]
            # Convert rank to 0-1 scale: (rank - 1) / (n - 1)
            if n > 1:
                result[orig_idx] = (avg_rank - 1) / (n - 1)
            else:
                result[orig_idx] = 0.5
        rank += j - i
        i = j

    return result


def compute_1y_return(prices: list[dict]) -> float | None:
    """Compute 1-year return from daily close prices.

    Expects prices sorted by date ascending, each {"date": "YYYY-MM-DD", "close": float}.
    """
    if len(prices) < 2:
        return None

    latest = prices[-1]["close"]
    # Find price ~1 year ago (252 trading days, or closest)
    target_idx = max(0, len(prices) - 252)
    start = prices[target_idx]["close"]

    if start == 0:
        return None
    return (latest / start) - 1.0


def compute_max_drawdown(prices: list[dict]) -> float | None:
    """Compute maximum drawdown over the price series.

    Returns a negative number (e.g., -0.15 for 15% drawdown).
    """
    if len(prices) < 2:
        return None

    closes = [p["close"] for p in prices]
    peak = closes[0]
    max_dd = 0.0

    for c in closes:
        if c > peak:
            peak = c
        dd = (c - peak) / peak if peak != 0 else 0
        if dd < max_dd:
            max_dd = dd

    return max_dd


def compute_ma_spread(prices: list[dict], window: int = 200) -> float | None:
    """Compute current price vs N-day moving average spread.

    Returns (current / SMA_N) - 1.
    """
    if len(prices) < window:
        return None

    closes = [p["close"] for p in prices]
    sma = sum(closes[-window:]) / window

    if sma == 0:
        return None
    return (closes[-1] / sma) - 1.0


async def _load_latest_macro_values(
    db: AsyncSession,
    countries: list[Country],
) -> dict[str, dict[str, float | None]]:
    """Load the most recent value for each macro indicator for each country.

    Returns {iso2: {indicator_name: value}}.
    """
    result: dict[str, dict[str, float | None]] = {}

    for country in countries:
        values: dict[str, float | None] = {}
        for indicator_name in MACRO_INDICATORS:
            # Get latest point for this series
            query = (
                select(CountrySeriesPoint.value)
                .join(CountrySeries)
                .where(
                    CountrySeries.country_id == country.id,
                    CountrySeries.series_name == indicator_name,
                )
                .order_by(desc(CountrySeriesPoint.date))
                .limit(1)
            )
            row = await db.execute(query)
            val = row.scalar_one_or_none()
            values[indicator_name] = float(val) if val is not None else None
        result[country.iso2] = values

    return result


async def _load_equity_prices(
    db: AsyncSession,
    countries: list[Country],
) -> dict[str, list[dict]]:
    """Load equity close prices for each country.

    Returns {iso2: [{"date": "YYYY-MM-DD", "close": float}, ...]}.
    """
    result: dict[str, list[dict]] = {}

    for country in countries:
        query = (
            select(CountrySeriesPoint.date, CountrySeriesPoint.value)
            .join(CountrySeries)
            .where(
                CountrySeries.country_id == country.id,
                CountrySeries.series_name == "equity_close",
            )
            .order_by(CountrySeriesPoint.date)
        )
        rows = await db.execute(query)
        prices = [
            {"date": str(r.date), "close": float(r.value)}
            for r in rows.all()
        ]
        result[country.iso2] = prices

    return result


async def _load_stability_values(
    db: AsyncSession,
    countries: list[Country],
) -> dict[str, float | None]:
    """Load the latest stability value for each country.

    Returns {iso2: float | None}.
    """
    result: dict[str, float | None] = {}

    for country in countries:
        query = (
            select(CountrySeriesPoint.value)
            .join(CountrySeries)
            .where(
                CountrySeries.country_id == country.id,
                CountrySeries.series_name == "stability",
            )
            .order_by(desc(CountrySeriesPoint.date))
            .limit(1)
        )
        row = await db.execute(query)
        val = row.scalar_one_or_none()
        result[country.iso2] = float(val) if val is not None else None

    return result


async def _load_point_ids_for_country(
    db: AsyncSession,
    country: Country,
) -> list[str]:
    """Load all point IDs for a country (for evidence tracking)."""
    query = (
        select(CountrySeriesPoint.id)
        .join(CountrySeries)
        .where(CountrySeries.country_id == country.id)
    )
    rows = await db.execute(query)
    return [str(r[0]) for r in rows.all()]


def _compute_macro_subscores(
    macro_data: dict[str, dict[str, float | None]],
) -> dict[str, float]:
    """Given {iso2: {indicator: value}}, return {iso2: macro_score_0_to_100}."""
    iso_codes = list(macro_data.keys())
    if not iso_codes:
        return {}

    # For each indicator, collect values and rank
    indicator_ranks: dict[str, dict[str, float]] = {}  # indicator -> {iso2: rank}

    for indicator, higher_is_better in MACRO_INDICATORS.items():
        values = [macro_data[iso].get(indicator) for iso in iso_codes]
        ranks = percentile_rank(values, higher_is_better=higher_is_better)
        indicator_ranks[indicator] = dict(zip(iso_codes, ranks))

    # Average across indicators for each country
    scores: dict[str, float] = {}
    for iso in iso_codes:
        ranks = [indicator_ranks[ind][iso] for ind in MACRO_INDICATORS]
        scores[iso] = (sum(ranks) / len(ranks)) * 100
    return scores


def _compute_market_subscores(
    prices_data: dict[str, list[dict]],
) -> dict[str, float]:
    """Given {iso2: [{date, close}]}, compute market sub-scores."""
    iso_codes = list(prices_data.keys())
    if not iso_codes:
        return {}

    returns = [compute_1y_return(prices_data[iso]) for iso in iso_codes]
    drawdowns = [compute_max_drawdown(prices_data[iso]) for iso in iso_codes]
    ma_spreads = [compute_ma_spread(prices_data[iso]) for iso in iso_codes]

    return_ranks = percentile_rank(returns, higher_is_better=True)
    # For drawdowns: less negative is better, so higher_is_better=True
    drawdown_ranks = percentile_rank(drawdowns, higher_is_better=True)
    ma_ranks = percentile_rank(ma_spreads, higher_is_better=True)

    scores: dict[str, float] = {}
    for i, iso in enumerate(iso_codes):
        avg = (return_ranks[i] + drawdown_ranks[i] + ma_ranks[i]) / 3
        scores[iso] = avg * 100

    return scores


async def compute_country_scores(
    db: AsyncSession,
    countries: list[Country],
    as_of: date,
    log_fn: Callable[[str], None],
) -> list[CountryScore]:
    """Compute scores for all countries.

    Must be called with all countries at once for percentile ranking.
    """
    log_fn(f"Loading macro data for {len(countries)} countries...")
    macro_data = await _load_latest_macro_values(db, countries)

    log_fn("Loading equity price data...")
    prices_data = await _load_equity_prices(db, countries)

    log_fn("Loading stability data...")
    stability_data = await _load_stability_values(db, countries)

    log_fn("Computing macro sub-scores...")
    macro_scores = _compute_macro_subscores(macro_data)

    log_fn("Computing market sub-scores...")
    market_scores = _compute_market_subscores(prices_data)

    # Stability sub-scores: value * 100
    stability_scores: dict[str, float] = {}
    for iso in [c.iso2 for c in countries]:
        val = stability_data.get(iso)
        stability_scores[iso] = (val * 100) if val is not None else 50.0

    # Composite scores
    w = COUNTRY_WEIGHTS
    results: list[CountryScore] = []

    for country in countries:
        iso = country.iso2
        macro = macro_scores.get(iso, 50.0)
        market = market_scores.get(iso, 50.0)
        stability = stability_scores.get(iso, 50.0)
        overall = w["macro"] * macro + w["market"] * market + w["stability"] * stability

        # Build component data for transparency
        component = {
            "macro_indicators": macro_data.get(iso, {}),
            "market_metrics": {
                "return_1y": compute_1y_return(prices_data.get(iso, [])),
                "max_drawdown": compute_max_drawdown(prices_data.get(iso, [])),
                "ma_spread": compute_ma_spread(prices_data.get(iso, [])),
            },
            "stability_value": stability_data.get(iso),
        }

        point_ids = await _load_point_ids_for_country(db, country)

        score = CountryScore(
            country_id=country.id,
            as_of=as_of,
            calc_version=COUNTRY_CALC_VERSION,
            macro_score=Decimal(str(round(macro, 2))),
            market_score=Decimal(str(round(market, 2))),
            stability_score=Decimal(str(round(stability, 2))),
            overall_score=Decimal(str(round(overall, 2))),
            component_data=component,
            point_ids=point_ids,
        )
        results.append(score)

        log_fn(f"  {iso}: overall={overall:.1f} (macro={macro:.1f}, market={market:.1f}, stability={stability:.1f})")

    return results


async def detect_country_risks(
    db: AsyncSession,
    country: Country,
    score: CountryScore,
    as_of: date,
    log_fn: Callable[[str], None],
) -> list[CountryRiskRegister]:
    """Detect risks based on threshold rules."""
    risks: list[CountryRiskRegister] = []
    component = score.component_data or {}
    macro = component.get("macro_indicators", {})

    # High inflation
    inflation = macro.get("inflation")
    if inflation is not None and inflation > 5:
        severity = "high" if inflation > 10 else "medium"
        risks.append(CountryRiskRegister(
            country_id=country.id,
            risk_type="high_inflation",
            severity=severity,
            description=f"Inflation at {inflation:.1f}%",
            detected_at=as_of,
        ))

    # High debt
    debt = macro.get("govt_debt_gdp")
    if debt is not None and debt > 100:
        severity = "high" if debt > 150 else "medium"
        risks.append(CountryRiskRegister(
            country_id=country.id,
            risk_type="high_debt",
            severity=severity,
            description=f"Government debt at {debt:.1f}% of GDP",
            detected_at=as_of,
        ))

    # Market drawdown
    market_metrics = component.get("market_metrics", {})
    drawdown = market_metrics.get("max_drawdown")
    if drawdown is not None and drawdown < -0.20:
        severity = "high" if drawdown < -0.30 else "medium"
        risks.append(CountryRiskRegister(
            country_id=country.id,
            risk_type="market_drawdown",
            severity=severity,
            description=f"Max drawdown of {drawdown:.1%}",
            detected_at=as_of,
        ))

    # Low overall score
    if float(score.overall_score) < 30:
        risks.append(CountryRiskRegister(
            country_id=country.id,
            risk_type="low_overall_score",
            severity="high",
            description=f"Overall score of {float(score.overall_score):.1f}",
            detected_at=as_of,
        ))

    if risks:
        log_fn(f"  {country.iso2}: {len(risks)} risk(s) detected")

    return risks
