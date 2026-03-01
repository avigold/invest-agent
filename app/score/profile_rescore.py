"""Rescore recommendations using a custom scoring profile.

Pure functions that operate on already-fetched data.
No DB writes — rescoring is ephemeral.
"""
from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanyScore, Country, CountryScore
from app.score.absolute import absolute_score
from app.score.profile_schema import ScoringProfileConfig
from app.score.versions import (
    COMPANY_CALC_VERSION,
    COUNTRY_CALC_VERSION,
    FUNDAMENTAL_ABSOLUTE_THRESHOLDS,
    MACRO_ABSOLUTE_THRESHOLDS,
    MARKET_ABSOLUTE_THRESHOLDS,
)


def _weighted_average(
    values: dict[str, float | None],
    weights: dict[str, float],
    thresholds: dict[str, dict],
) -> float:
    """Compute weighted average of absolute-scored indicator values.

    Args:
        values: Raw indicator values (may contain None).
        weights: Relative weights per indicator (will be normalized).
        thresholds: Absolute scoring thresholds per indicator.

    Returns:
        Weighted average score (0-100).
    """
    total_weight = 0.0
    weighted_sum = 0.0

    for name, weight in weights.items():
        if weight <= 0:
            continue
        value = values.get(name)
        th = thresholds.get(name)
        if th is None:
            continue
        score = absolute_score(value, th["floor"], th["ceiling"], th["higher_is_better"])
        weighted_sum += score * weight
        total_weight += weight

    if total_weight == 0:
        return 50.0
    return weighted_sum / total_weight


def _rescore_country(
    component_data: dict,
    profile: ScoringProfileConfig,
) -> float:
    """Rescore a country using profile weights and stored component_data."""
    macro_indicators = component_data.get("macro_indicators", {})
    market_metrics = component_data.get("market_metrics", {})
    stability_value = component_data.get("stability_value")

    macro_score = _weighted_average(
        macro_indicators,
        profile.country_macro_indicator_weights,
        MACRO_ABSOLUTE_THRESHOLDS,
    )
    market_score = _weighted_average(
        market_metrics,
        profile.country_market_metric_weights,
        MARKET_ABSOLUTE_THRESHOLDS,
    )
    stability_score = (stability_value * 100) if stability_value is not None else 50.0

    w = profile.country_weights
    return w["macro"] * macro_score + w["market"] * market_score + w["stability"] * stability_score


def _rescore_company(
    component_data: dict,
    profile: ScoringProfileConfig,
) -> float:
    """Rescore a company using profile weights and stored component_data."""
    fundamental_ratios = component_data.get("fundamental_ratios", {})
    market_metrics = component_data.get("market_metrics", {})

    has_fundamentals = bool(fundamental_ratios)

    if has_fundamentals:
        fundamental_score = _weighted_average(
            fundamental_ratios,
            profile.company_fundamental_ratio_weights,
            FUNDAMENTAL_ABSOLUTE_THRESHOLDS,
        )
        w = profile.company_weights
    else:
        fundamental_score = 50.0
        w = {"fundamental": 0.0, "market": 1.0}

    market_score = _weighted_average(
        market_metrics,
        profile.company_market_metric_weights,
        MARKET_ABSOLUTE_THRESHOLDS,
    )

    return w["fundamental"] * fundamental_score + w["market"] * market_score


def rescore_recommendations(
    base_recommendations: list[dict],
    component_bundles: dict,
    profile: ScoringProfileConfig,
) -> list[dict]:
    """Rescore and reorder recommendations using a custom profile.

    Args:
        base_recommendations: Output of compute_recommendations().
        component_bundles: {"country": {iso2: component_data}, "company": {ticker: component_data}}.
        profile: The user's scoring profile config.

    Returns:
        New list of recommendation dicts, rescored, reclassified, and re-ranked.
    """
    rec_w = profile.recommendation_weights
    buy_threshold = profile.thresholds["buy"]
    sell_threshold = profile.thresholds["sell"]

    country_components = component_bundles.get("country", {})
    company_components = component_bundles.get("company", {})

    rescored = []
    for rec in base_recommendations:
        new_rec = dict(rec)

        # Rescore country
        country_cd = country_components.get(rec["country_iso2"])
        if country_cd:
            new_rec["country_score"] = round(_rescore_country(country_cd, profile), 2)

        # Industry: pass through unchanged
        # new_rec["industry_score"] stays as-is

        # Rescore company
        company_cd = company_components.get(rec["ticker"])
        if company_cd:
            new_rec["company_score"] = round(_rescore_company(company_cd, profile), 2)

        # Recompute composite
        composite = (
            rec_w["country"] * new_rec["country_score"]
            + rec_w["industry"] * new_rec["industry_score"]
            + rec_w["company"] * new_rec["company_score"]
        )
        new_rec["composite_score"] = round(composite, 2)

        # Reclassify
        if composite > buy_threshold:
            new_rec["classification"] = "Buy"
        elif composite < sell_threshold:
            new_rec["classification"] = "Sell"
        else:
            new_rec["classification"] = "Hold"

        rescored.append(new_rec)

    # Re-sort and re-rank
    rescored.sort(key=lambda r: r["composite_score"], reverse=True)
    total = len(rescored)
    for i, rec in enumerate(rescored, 1):
        rec["rank"] = i
        rec["rank_total"] = total

    return rescored


async def load_score_component_data(db: AsyncSession) -> dict:
    """Load component_data from latest CountryScore and CompanyScore rows.

    Returns:
        {"country": {iso2: component_data}, "company": {ticker: component_data}}
    """
    country_data: dict[str, dict] = {}
    company_data: dict[str, dict] = {}

    # Load latest country scores with component_data
    countries_q = select(Country)
    countries_result = await db.execute(countries_q)
    for country in countries_result.scalars().all():
        cs_q = (
            select(CountryScore)
            .where(
                CountryScore.country_id == country.id,
                CountryScore.calc_version == COUNTRY_CALC_VERSION,
            )
            .order_by(desc(CountryScore.as_of))
            .limit(1)
        )
        cs_result = await db.execute(cs_q)
        cs = cs_result.scalar_one_or_none()
        if cs and cs.component_data:
            country_data[country.iso2] = cs.component_data

    # Load latest company scores with component_data
    latest_date_q = (
        select(CompanyScore.as_of)
        .where(CompanyScore.calc_version == COMPANY_CALC_VERSION)
        .order_by(desc(CompanyScore.as_of))
        .limit(1)
    )
    result = await db.execute(latest_date_q)
    latest_date = result.scalar_one_or_none()

    if latest_date:
        scores_q = (
            select(CompanyScore, Company)
            .join(Company, CompanyScore.company_id == Company.id)
            .where(
                CompanyScore.as_of == latest_date,
                CompanyScore.calc_version == COMPANY_CALC_VERSION,
            )
        )
        result = await db.execute(scores_q)
        for company_score, company in result.all():
            if company_score.component_data:
                company_data[company.ticker] = company_score.component_data

    return {"country": country_data, "company": company_data}
