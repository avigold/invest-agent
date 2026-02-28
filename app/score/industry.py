"""Deterministic industry scoring engine — rubric-based macro sensitivity."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Country,
    CountrySeries,
    CountrySeriesPoint,
    Industry,
    IndustryRiskRegister,
    IndustryScore,
)
from app.score.country import percentile_rank
from app.score.versions import INDUSTRY_CALC_VERSION

_RUBRIC_PATH = Path(__file__).resolve().parents[2] / "config" / "sector_macro_sensitivity_v1.json"

# Map rubric indicator names → DB series_name
_INDICATOR_TO_SERIES: dict[str, str] = {
    "gdp_growth_pct": "gdp_growth",
    "inflation_pct": "inflation",
    "unemployment_pct": "unemployment",
    "govt_debt_gdp_pct": "govt_debt_gdp",
    "current_account_gdp_pct": "current_account_gdp",
    "fdi_gdp_pct": "fdi_gdp",
    "central_bank_rate_pct": "fedfunds",
    "hy_credit_spread_bps": "hy_spread",
    "yield_curve_10y2y_bps": "yield_curve",
    "stability_index": "stability",
}


def load_rubric() -> dict:
    """Load the sector macro sensitivity rubric config."""
    return json.loads(_RUBRIC_PATH.read_text())


async def load_macro_for_country(
    db: AsyncSession,
    country: Country,
) -> dict[str, float | None]:
    """Load latest value for each rubric indicator from country series.

    Returns {rubric_indicator_name: value_or_None}.
    """
    macro: dict[str, float | None] = {}

    for rubric_name, series_name in _INDICATOR_TO_SERIES.items():
        query = (
            select(CountrySeriesPoint.value)
            .join(CountrySeries)
            .where(
                CountrySeries.country_id == country.id,
                CountrySeries.series_name == series_name,
            )
            .order_by(desc(CountrySeriesPoint.date))
            .limit(1)
        )
        row = await db.execute(query)
        val = row.scalar_one_or_none()
        macro[rubric_name] = float(val) if val is not None else None

    return macro


def evaluate_rubric(
    rubric: dict,
    macro_data: dict[str, float | None],
) -> dict[str, dict]:
    """Evaluate the rubric for all sectors against a country's macro data.

    Returns {sector_key: {"raw_score": int, "max_possible": int,
             "min_possible": int, "signals": list[dict]}}.
    """
    thresholds = rubric["thresholds"]
    results: dict[str, dict] = {}

    for sector_key, sector_cfg in rubric["sectors"].items():
        signals: list[dict] = []
        raw_score = 0
        n_indicators = len(sector_cfg["sensitivities"])

        for sens in sector_cfg["sensitivities"]:
            indicator = sens["indicator"]
            favorable_when = sens["favorable_when"]
            value = macro_data.get(indicator)
            threshold_cfg = thresholds[indicator]
            threshold = threshold_cfg["threshold"]

            if value is None:
                # Missing data: contribute 0 (neutral)
                signals.append({
                    "indicator": indicator,
                    "value": None,
                    "threshold": threshold,
                    "favorable_when": favorable_when,
                    "signal": 0,
                    "reason": "missing_data",
                })
                continue

            # Determine if the current value is "high" or "low" relative to threshold
            is_high = value >= threshold

            # Determine signal: +1 if favorable, -1 if unfavorable
            if favorable_when == "high":
                signal = 1 if is_high else -1
            else:  # favorable_when == "low"
                signal = 1 if not is_high else -1

            raw_score += signal
            signals.append({
                "indicator": indicator,
                "value": round(value, 2),
                "threshold": threshold,
                "favorable_when": favorable_when,
                "signal": signal,
            })

        results[sector_key] = {
            "raw_score": raw_score,
            "max_possible": n_indicators,
            "min_possible": -n_indicators,
            "signals": signals,
        }

    return results


async def load_point_ids_for_indicators(
    db: AsyncSession,
    country: Country,
    indicator_series_names: list[str],
) -> list[str]:
    """Load point IDs for the specific series used in industry scoring."""
    if not indicator_series_names:
        return []

    series_names = [_INDICATOR_TO_SERIES.get(name, name) for name in indicator_series_names]

    query = (
        select(CountrySeriesPoint.id)
        .join(CountrySeries)
        .where(
            CountrySeries.country_id == country.id,
            CountrySeries.series_name.in_(series_names),
        )
    )
    rows = await db.execute(query)
    return [str(r[0]) for r in rows.all()]


async def compute_industry_scores(
    db: AsyncSession,
    industries: list[Industry],
    countries: list[Country],
    as_of: date,
    log_fn: Callable[[str], None],
) -> list[IndustryScore]:
    """Compute rubric-based scores for all industry×country combinations.

    All 110 combinations are percentile-ranked together.
    """
    rubric = load_rubric()

    # Load macro data for each country
    log_fn(f"Loading macro data for {len(countries)} countries...")
    country_macro: dict[str, dict[str, float | None]] = {}
    country_by_iso: dict[str, Country] = {}
    for country in countries:
        country_macro[country.iso2] = await load_macro_for_country(db, country)
        country_by_iso[country.iso2] = country

    # Build industry lookup: gics_code → Industry
    industry_by_gics: dict[str, Industry] = {ind.gics_code: ind for ind in industries}

    # Evaluate rubric for each country × sector
    log_fn("Evaluating rubric for all country × sector combinations...")
    # Collect all (sector_key, iso2, raw_score, component) tuples
    all_combos: list[tuple[str, str, int, dict]] = []

    for country in countries:
        macro = country_macro[country.iso2]
        evaluation = evaluate_rubric(rubric, macro)

        for sector_key, result in evaluation.items():
            all_combos.append((sector_key, country.iso2, result["raw_score"], result))

    # Percentile-rank all raw scores together (higher raw = more favorable = higher rank)
    raw_scores = [float(combo[2]) for combo in all_combos]
    ranks = percentile_rank(raw_scores, higher_is_better=True)

    # Build IndustryScore objects
    log_fn(f"Building {len(all_combos)} industry scores...")
    scores: list[IndustryScore] = []

    for i, (sector_key, iso2, raw_score, component) in enumerate(all_combos):
        sector_cfg = rubric["sectors"][sector_key]
        gics_code = sector_cfg["gics_code"]
        industry = industry_by_gics.get(gics_code)
        country = country_by_iso[iso2]

        if industry is None:
            continue

        overall = round(ranks[i] * 100, 2)

        # Get point IDs for evidence tracking
        indicator_names = [s["indicator"] for s in component["signals"]]
        point_ids = await load_point_ids_for_indicators(db, country, indicator_names)

        # Enrich component_data with country macro summary
        macro_summary = {
            _INDICATOR_TO_SERIES[k]: v
            for k, v in country_macro[iso2].items()
            if v is not None
        }
        component["country_macro_summary"] = macro_summary

        score = IndustryScore(
            industry_id=industry.id,
            country_id=country.id,
            as_of=as_of,
            calc_version=INDUSTRY_CALC_VERSION,
            rubric_score=Decimal(str(raw_score)),
            overall_score=Decimal(str(overall)),
            component_data=component,
            point_ids=point_ids,
        )
        scores.append(score)

        log_fn(f"  {sector_cfg['label']} × {iso2}: raw={raw_score}, overall={overall:.1f}")

    return scores


def detect_industry_risks(
    industry: Industry,
    country: Country,
    score: IndustryScore,
    as_of: date,
    log_fn: Callable[[str], None],
) -> list[IndustryRiskRegister]:
    """Detect risks for an industry×country combination based on threshold rules."""
    risks: list[IndustryRiskRegister] = []
    overall = float(score.overall_score)
    component = score.component_data or {}

    # Macro headwinds: overall score below 30
    if overall < 30:
        severity = "high" if overall < 15 else "medium"
        risks.append(IndustryRiskRegister(
            industry_id=industry.id,
            country_id=country.id,
            risk_type="macro_headwinds",
            severity=severity,
            description=f"Unfavorable macro environment (score {overall:.1f}/100)",
            detected_at=as_of,
        ))

    # All signals negative
    signals = component.get("signals", [])
    active_signals = [s for s in signals if s.get("signal") != 0]
    if active_signals and all(s["signal"] == -1 for s in active_signals):
        risks.append(IndustryRiskRegister(
            industry_id=industry.id,
            country_id=country.id,
            risk_type="all_signals_negative",
            severity="high",
            description="All macro indicators are unfavorable for this sector",
            detected_at=as_of,
        ))

    if risks:
        log_fn(f"  {industry.name} × {country.iso2}: {len(risks)} risk(s)")

    return risks
