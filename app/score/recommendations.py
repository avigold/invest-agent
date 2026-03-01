"""On-the-fly recommendation computation from stored scores."""
from __future__ import annotations

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Company,
    CompanyScore,
    Country,
    CountryScore,
    Industry,
    IndustryScore,
)
from app.score.versions import (
    COMPANY_CALC_VERSION,
    COUNTRY_CALC_VERSION,
    INDUSTRY_CALC_VERSION,
    RECOMMENDATION_THRESHOLDS,
    RECOMMENDATION_VERSION,
    RECOMMENDATION_WEIGHTS,
)


def classify(composite_score: float) -> str:
    """Classify a composite score into Buy/Hold/Sell."""
    if composite_score > RECOMMENDATION_THRESHOLDS["buy"]:
        return "Buy"
    if composite_score < RECOMMENDATION_THRESHOLDS["sell"]:
        return "Sell"
    return "Hold"


async def compute_recommendations(db: AsyncSession) -> list[dict]:
    """Compute recommendations for all scored companies.

    Joins latest CompanyScore, CountryScore, and IndustryScore to produce
    a composite score and classification for each company.

    Returns list of dicts sorted by composite_score desc.
    """
    # Get the latest company score date
    latest_date_q = (
        select(CompanyScore.as_of)
        .where(CompanyScore.calc_version == COMPANY_CALC_VERSION)
        .order_by(desc(CompanyScore.as_of))
        .limit(1)
    )
    result = await db.execute(latest_date_q)
    latest_date = result.scalar_one_or_none()
    if latest_date is None:
        return []

    # Load all company scores for the latest date
    scores_q = (
        select(CompanyScore, Company)
        .join(Company, CompanyScore.company_id == Company.id)
        .where(
            CompanyScore.as_of == latest_date,
            CompanyScore.calc_version == COMPANY_CALC_VERSION,
        )
    )
    result = await db.execute(scores_q)
    score_rows = result.all()

    if not score_rows:
        return []

    # Build lookup: country_iso2 -> latest CountryScore.overall_score
    country_scores: dict[str, float] = {}
    countries_q = select(Country)
    countries_result = await db.execute(countries_q)
    for country in countries_result.scalars().all():
        cs_q = (
            select(CountryScore.overall_score)
            .where(
                CountryScore.country_id == country.id,
                CountryScore.calc_version == COUNTRY_CALC_VERSION,
            )
            .order_by(desc(CountryScore.as_of))
            .limit(1)
        )
        cs_result = await db.execute(cs_q)
        cs_val = cs_result.scalar_one_or_none()
        if cs_val is not None:
            country_scores[country.iso2] = float(cs_val)

    # Build lookup: (gics_code, country_iso2) -> latest IndustryScore.overall_score
    industry_scores: dict[tuple[str, str], float] = {}
    is_q = (
        select(IndustryScore, Industry, Country)
        .join(Industry, IndustryScore.industry_id == Industry.id)
        .join(Country, IndustryScore.country_id == Country.id)
        .where(IndustryScore.calc_version == INDUSTRY_CALC_VERSION)
    )
    is_result = await db.execute(is_q)
    # Group by (gics_code, iso2), keep latest
    _seen: dict[tuple[str, str], str] = {}  # track latest as_of
    for is_row, industry, country in is_result.all():
        key = (industry.gics_code, country.iso2)
        as_of_str = str(is_row.as_of)
        if key not in _seen or as_of_str > _seen[key]:
            _seen[key] = as_of_str
            industry_scores[key] = float(is_row.overall_score)

    # Compute composite for each company
    w = RECOMMENDATION_WEIGHTS
    recommendations = []

    for company_score, company in score_rows:
        cs = country_scores.get(company.country_iso2, 50.0)
        is_key = (company.gics_code, company.country_iso2)
        ind_s = industry_scores.get(is_key, 50.0)
        comp_s = float(company_score.overall_score)

        composite = w["country"] * cs + w["industry"] * ind_s + w["company"] * comp_s
        composite = round(composite, 2)

        recommendations.append({
            "ticker": company.ticker,
            "name": company.name,
            "country_iso2": company.country_iso2,
            "gics_code": company.gics_code,
            "company_score": comp_s,
            "country_score": cs,
            "industry_score": ind_s,
            "composite_score": composite,
            "classification": classify(composite),
            "as_of": str(company_score.as_of),
            "recommendation_version": RECOMMENDATION_VERSION,
        })

    # Sort by composite_score desc and assign rank
    recommendations.sort(key=lambda r: r["composite_score"], reverse=True)
    total = len(recommendations)
    for i, rec in enumerate(recommendations, 1):
        rec["rank"] = i
        rec["rank_total"] = total

    return recommendations
