"""Score current companies against a winner profile from screening matches.

The winner profile captures what historical outperformers looked like BEFORE
their run (fundamentals_at_start). We then find companies today whose
current fundamentals resemble that pre-run archetype.
"""
from __future__ import annotations

import math
import statistics
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanyScore
from app.screen.common_features import GICS_SECTORS

# Metrics that exist in both the screener snapshot (fundamentals_at_start)
# and in CompanyScore.component_data["fundamental_ratios"].
COMPARABLE_METRICS = {"roe", "net_margin", "debt_equity"}

# Metrics where lower values are better (inverted scoring).
INVERTED_METRICS = {"debt_equity"}

# Maximum gap (in days) between the fiscal date and the window start date
# for fundamentals to be considered "period-appropriate".
MAX_FISCAL_GAP_DAYS = 365 * 3  # 3 years

# Sector match bonus (additive, on top of fundamental score).
SECTOR_BONUS = 0.10

# Minimum score to appear as a candidate.
MIN_CANDIDATE_SCORE = 0.20


def compute_winner_profile(
    matches: list[dict],
) -> dict[str, dict[str, float]]:
    """Compute P25/median/P75 for each fundamental metric across match fundamentals.

    Only includes fundamentals that are period-appropriate (fiscal date within
    MAX_FISCAL_GAP_DAYS of the window start). If no fiscal date metadata is
    available, the data is included but flagged.

    Args:
        matches: list of match dicts from ScreenResult.matches,
                 each with "fundamentals_at_start" dict

    Returns: {metric: {p25, median, p75, count, stale_count}}
             for metrics with >= 3 data points
    """
    metric_values: dict[str, list[float]] = {}
    stale_counts: dict[str, int] = {}

    for m in matches:
        fundas = m.get("fundamentals_at_start", {})
        if not fundas:
            continue

        # Check data freshness
        fiscal_gap = fundas.get("_fiscal_gap_days")
        is_stale = fiscal_gap is not None and fiscal_gap > MAX_FISCAL_GAP_DAYS

        for metric in COMPARABLE_METRICS:
            val = fundas.get(metric)
            if val is None:
                continue

            if is_stale:
                stale_counts[metric] = stale_counts.get(metric, 0) + 1
                continue  # Skip stale data from profile

            metric_values.setdefault(metric, []).append(val)

    profile: dict[str, dict[str, float]] = {}
    for metric, values in metric_values.items():
        if len(values) < 3:
            continue
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        profile[metric] = {
            "p25": sorted_vals[n // 4],
            "median": statistics.median(sorted_vals),
            "p75": sorted_vals[(3 * n) // 4],
            "count": n,
            "stale_count": stale_counts.get(metric, 0),
        }

    return profile


def _metric_proximity(
    val: float,
    p25: float,
    median: float,
    p75: float,
    inverted: bool = False,
) -> float:
    """Score how close a value is to the winner sweet spot.

    Returns 0.0–1.0 using Gaussian-like decay from the median.
    At median: 1.0. At P25/P75: ~0.78. At 2 IQR away: ~0.02.

    For inverted metrics (lower is better), values at or below median
    score 1.0 and decay upward from there.
    """
    iqr = p75 - p25
    if iqr <= 0:
        # Very tight distribution — use 20% of median as spread
        iqr = abs(median) * 0.2 or 0.01

    if inverted:
        if val <= median:
            return 1.0
        distance = (val - median) / iqr
    else:
        distance = (val - median) / iqr

    # Gaussian decay: e^(-d^2)
    return max(0.0, math.exp(-(distance * distance)))


def _score_company(
    fundamentals: dict[str, float | None],
    gics_code: str,
    winner_profile: dict[str, dict[str, float]],
    winner_sectors: set[str],
) -> tuple[float, list[str]]:
    """Score a single company against the winner profile.

    Uses graduated proximity scoring instead of binary in/out matching.
    Missing metrics count against the company (0 contribution but weight
    still counted), so companies with sparse data score lower.

    Returns (match_score 0–1, list of notable matching factor names).
    """
    if not winner_profile:
        return 0.0, []

    total_weight = 0.0
    total_score = 0.0
    matching_factors: list[str] = []

    for metric, bounds in winner_profile.items():
        val = fundamentals.get(metric)
        weight = 1.0
        total_weight += weight

        if val is None:
            continue  # 0 contribution, weight still counted

        proximity = _metric_proximity(
            val,
            bounds["p25"],
            bounds["median"],
            bounds["p75"],
            inverted=(metric in INVERTED_METRICS),
        )
        total_score += proximity * weight

        # Track as a matching factor if proximity is strong
        if proximity >= 0.5:
            matching_factors.append(metric)

    if total_weight == 0:
        return 0.0, []

    fundamental_score = total_score / total_weight

    # Sector bonus (additive, small)
    sector_label = GICS_SECTORS.get(gics_code, "")
    if sector_label in winner_sectors:
        matching_factors.append("sector")
        fundamental_score += SECTOR_BONUS

    score = min(1.0, fundamental_score)
    score = round(score, 4)

    if score < MIN_CANDIDATE_SCORE:
        return 0.0, []

    return score, matching_factors


async def score_candidates(
    db: AsyncSession,
    winner_profile: dict[str, dict[str, float]],
    winner_sectors: set[str],
    exclude_tickers: set[str],
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Score all DB companies against the winner profile.

    Returns top_n candidates sorted by match_score descending.
    Excludes tickers that were already in the screen matches.
    """
    from sqlalchemy import func

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

    for score, company in result:
        if company.ticker in exclude_tickers:
            continue

        cd = score.component_data or {}
        fundamentals = cd.get("fundamental_ratios", {})

        match_score, matching_factors = _score_company(
            fundamentals,
            company.gics_code or "",
            winner_profile,
            winner_sectors,
        )

        if match_score > 0:
            candidates.append({
                "ticker": company.ticker,
                "name": company.name,
                "country_iso2": company.country_iso2,
                "gics_code": company.gics_code or "",
                "match_score": match_score,
                "matching_factors": matching_factors,
                "current_fundamentals": {
                    k: round(v, 4) if v is not None else None
                    for k, v in fundamentals.items()
                },
                "current_score": float(score.overall_score),
            })

    candidates.sort(key=lambda c: c["match_score"], reverse=True)
    return candidates[:top_n]
