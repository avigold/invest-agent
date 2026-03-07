"""v2 candidate scorer — discrimination-weighted feature proximity.

Instead of matching against a winner profile with only 3 sparse fundamentals,
v2 uses the full contrast analysis to weight features by their separation score.
Features that actually discriminate winners from non-winners get more weight.
A catastrophe penalty reduces scores for companies resembling catastrophe profiles.
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanyScore
from app.screen.common_features import GICS_SECTORS
from app.screen.contrast import ContrastProfile, FeatureContrast


# Sector match bonus (additive)
SECTOR_BONUS = 0.10

# Catastrophe penalty factor — how much catastrophe similarity reduces the score
CATASTROPHE_PENALTY = 0.30

# Minimum score to appear as a candidate
MIN_CANDIDATE_SCORE = 0.15

# Mapping from contrast feature names to CompanyScore.component_data paths
FEATURE_MAP: dict[str, tuple[str, str]] = {
    # (section, key) in component_data
    "momentum_12m": ("market_metrics", "return_1y"),
    "max_dd_12m": ("market_metrics", "max_drawdown"),
    "ma_spread": ("market_metrics", "ma_spread"),
    "roe": ("fundamental_ratios", "roe"),
    "net_margin": ("fundamental_ratios", "net_margin"),
    "debt_equity": ("fundamental_ratios", "debt_equity"),
    "revenue_growth": ("fundamental_ratios", "revenue_growth"),
    "fcf_yield": ("fundamental_ratios", "fcf_yield"),
}


def _gaussian_proximity(val: float, target: float, spread: float) -> float:
    """Compute Gaussian proximity: 1.0 at target, decaying outward.

    spread is the characteristic width (typically IQR or similar).
    """
    if spread <= 0:
        spread = abs(target) * 0.2 or 0.01
    d = (val - target) / spread
    return math.exp(-(d * d))


def _score_feature(
    val: float | None,
    fc: FeatureContrast,
) -> float | None:
    """Score a single feature value against the contrast profile.

    Returns proximity score 0-1, or None if value is missing.
    """
    if val is None:
        return None

    # Use winner IQR as the spread
    iqr = fc.winner_p75 - fc.winner_p25
    if iqr <= 0:
        iqr = abs(fc.winner_median) * 0.2 or 0.01

    return _gaussian_proximity(val, fc.winner_median, iqr)


def _get_candidate_value(
    component_data: dict,
    feature: str,
) -> float | None:
    """Extract a feature value from CompanyScore.component_data."""
    mapping = FEATURE_MAP.get(feature)
    if not mapping:
        return None
    section, key = mapping
    data = component_data.get(section, {})
    val = data.get(key)
    if val is None:
        return None
    return float(val)


def _score_candidate(
    component_data: dict,
    gics_code: str,
    contrast: ContrastProfile,
    catastrophe_profile: ContrastProfile | None,
    winner_sectors: set[str],
) -> tuple[float, list[dict[str, Any]]]:
    """Score a single candidate using discrimination-weighted features.

    Returns (score 0-1, list of factor dicts with details).
    """
    if not contrast.features:
        return 0.0, []

    total_weighted_score = 0.0
    total_weight = 0.0
    factors: list[dict[str, Any]] = []

    for fc in contrast.features:
        val = _get_candidate_value(component_data, fc.feature)
        weight = fc.separation  # Weight by how discriminating this feature is

        if weight <= 0.01:
            continue  # Skip features with negligible separation

        total_weight += weight

        if val is None:
            continue  # Missing = 0 contribution, weight still counts

        proximity = _score_feature(val, fc)
        if proximity is None:
            continue

        total_weighted_score += proximity * weight

        if proximity >= 0.3:
            factors.append({
                "feature": fc.feature,
                "value": round(val, 4),
                "winner_median": round(fc.winner_median, 4),
                "proximity": round(proximity, 4),
                "separation": round(fc.separation, 4),
                "direction": fc.direction,
            })

    if total_weight <= 0:
        return 0.0, []

    score = total_weighted_score / total_weight

    # Catastrophe penalty
    catastrophe_similarity = 0.0
    if catastrophe_profile and catastrophe_profile.features:
        cat_total = 0.0
        cat_weight = 0.0
        for cfc in catastrophe_profile.features:
            val = _get_candidate_value(component_data, cfc.feature)
            if val is None or cfc.separation <= 0.01:
                continue

            cat_iqr = cfc.winner_p75 - cfc.winner_p25
            if cat_iqr <= 0:
                cat_iqr = abs(cfc.winner_median) * 0.2 or 0.01

            prox = _gaussian_proximity(val, cfc.winner_median, cat_iqr)
            cat_total += prox * cfc.separation
            cat_weight += cfc.separation

        if cat_weight > 0:
            catastrophe_similarity = cat_total / cat_weight
            score -= catastrophe_similarity * CATASTROPHE_PENALTY

    # Sector bonus
    sector_label = GICS_SECTORS.get(gics_code, "")
    if sector_label in winner_sectors:
        factors.append({
            "feature": "sector",
            "value": sector_label,
            "proximity": 1.0,
            "separation": SECTOR_BONUS,
            "direction": "match",
        })
        score += SECTOR_BONUS

    score = max(0.0, min(1.0, score))

    if score < MIN_CANDIDATE_SCORE:
        return 0.0, []

    return round(score, 4), factors


async def score_candidates_v2(
    db: AsyncSession,
    contrast: ContrastProfile,
    catastrophe_profile: ContrastProfile | None,
    winner_sectors: set[str],
    exclude_tickers: set[str],
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Score all DB companies using discrimination-weighted contrast features.

    Returns top_n candidates sorted by score descending.
    """
    subq = (
        select(
            CompanyScore.company_id,
            func.max(CompanyScore.as_of).label("max_as_of"),
        )
        .group_by(CompanyScore.company_id)
        .subquery()
    )

    result = await db.execute(
        select(CompanyScore, Company)
        .join(Company, CompanyScore.company_id == Company.id)
        .join(
            subq,
            (CompanyScore.company_id == subq.c.company_id)
            & (CompanyScore.as_of == subq.c.max_as_of),
        )
    )

    candidates: list[dict[str, Any]] = []

    for company_score, company in result:
        if company.ticker in exclude_tickers:
            continue

        cd = company_score.component_data or {}

        score, factors = _score_candidate(
            cd,
            company.gics_code or "",
            contrast,
            catastrophe_profile,
            winner_sectors,
        )

        if score > 0:
            # Extract current values for display
            fr = cd.get("fundamental_ratios", {})
            mm = cd.get("market_metrics", {})

            candidates.append({
                "ticker": company.ticker,
                "name": company.name,
                "country_iso2": company.country_iso2,
                "gics_code": company.gics_code or "",
                "match_score": score,
                "matching_factors": factors,
                "current_fundamentals": {
                    k: round(v, 4) if v is not None else None
                    for k, v in fr.items()
                },
                "current_market": {
                    k: round(v, 4) if v is not None else None
                    for k, v in mm.items()
                },
                "current_score": float(company_score.overall_score),
            })

    candidates.sort(key=lambda c: c["match_score"], reverse=True)
    return candidates[:top_n]
