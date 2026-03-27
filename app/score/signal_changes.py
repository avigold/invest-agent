"""Snapshot-and-diff classification change detection.

Captures current Buy/Hold/Sell classifications before and after a scoring run,
then logs any flips to the signal_changes table.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Country, CountryScore, Industry, IndustryScore,
    PredictionScore, SignalChange,
)
from app.score.feature_scorer import score_from_features
from app.score.recommendations import classify, compute_recommendations
from app.score.versions import (
    COUNTRY_CALC_VERSION, INDUSTRY_CALC_VERSION,
    RECOMMENDATION_WEIGHTS,
)

if TYPE_CHECKING:
    from sqlalchemy import func as sa_func  # noqa: F401

# Same mapping as routes_predictions.py
_SECTOR_TO_GICS: dict[str, str] = {
    "Energy": "10", "Materials": "15", "Industrials": "20",
    "Consumer Discretionary": "25", "Consumer Staples": "30",
    "Health Care": "35", "Financials": "40",
    "Information Technology": "45", "Communication Services": "50",
    "Utilities": "55", "Real Estate": "60",
}

# Type alias for a snapshot: {ticker: (classification, composite_score, company_name)}
Snapshot = dict[str, tuple[str, float, str]]


async def snapshot_deterministic(db: AsyncSession) -> Snapshot:
    """Snapshot current deterministic classifications for all companies."""
    recs = await compute_recommendations(db)
    return {
        r["ticker"]: (r["classification"], r["composite_score"], r["name"])
        for r in recs
    }


async def _load_country_scores(db: AsyncSession) -> dict[str, float]:
    """Load latest country scores as {iso2: overall_score}."""
    from sqlalchemy import func

    latest_sq = (
        select(
            CountryScore.country_id,
            func.max(CountryScore.as_of).label("max_as_of"),
        )
        .where(CountryScore.calc_version == COUNTRY_CALC_VERSION)
        .group_by(CountryScore.country_id)
        .subquery()
    )
    result = await db.execute(
        select(Country.iso2, CountryScore.overall_score)
        .join(CountryScore, CountryScore.country_id == Country.id)
        .join(
            latest_sq,
            (CountryScore.country_id == latest_sq.c.country_id)
            & (CountryScore.as_of == latest_sq.c.max_as_of),
        )
        .where(CountryScore.calc_version == COUNTRY_CALC_VERSION)
    )
    return {iso2: float(score) for iso2, score in result.all()}


async def _load_industry_scores(
    db: AsyncSession,
) -> dict[tuple[str, str], float]:
    """Load latest industry scores as {(gics_code, iso2): overall_score}."""
    from sqlalchemy import func

    latest_sq = (
        select(
            IndustryScore.industry_id,
            IndustryScore.country_id,
            func.max(IndustryScore.as_of).label("max_as_of"),
        )
        .where(IndustryScore.calc_version == INDUSTRY_CALC_VERSION)
        .group_by(IndustryScore.industry_id, IndustryScore.country_id)
        .subquery()
    )
    result = await db.execute(
        select(Industry.gics_code, Country.iso2, IndustryScore.overall_score)
        .join(IndustryScore, IndustryScore.industry_id == Industry.id)
        .join(Country, IndustryScore.country_id == Country.id)
        .join(
            latest_sq,
            (IndustryScore.industry_id == latest_sq.c.industry_id)
            & (IndustryScore.country_id == latest_sq.c.country_id)
            & (IndustryScore.as_of == latest_sq.c.max_as_of),
        )
        .where(IndustryScore.calc_version == INDUSTRY_CALC_VERSION)
    )
    return {(gics, iso2): float(score) for gics, iso2, score in result.all()}


async def snapshot_ml(
    db: AsyncSession, model_id: uuid.UUID,
) -> Snapshot:
    """Snapshot current ML classifications for all scores of a model."""
    result = await db.execute(
        select(
            PredictionScore.ticker,
            PredictionScore.company_name,
            PredictionScore.country,
            PredictionScore.sector,
            PredictionScore.feature_values,
        ).where(PredictionScore.model_id == model_id)
    )
    rows = result.all()
    if not rows:
        return {}

    cs = await _load_country_scores(db)
    ins = await _load_industry_scores(db)
    w = RECOMMENDATION_WEIGHTS

    snap: Snapshot = {}
    for ticker, company_name, country, sector, feature_values in rows:
        det = score_from_features(feature_values or {})
        country_iso2 = country or ""
        gics = _SECTOR_TO_GICS.get(sector or "", "")
        cs_val = cs.get(country_iso2, 10.0)
        ind_val = ins.get((gics, country_iso2), 10.0)
        composite = round(
            w["country"] * cs_val + w["industry"] * ind_val
            + w["company"] * det["company_score"], 2
        )
        classification = classify(composite)
        snap[ticker] = (classification, composite, company_name or "")
    return snap


async def detect_and_log_changes(
    db: AsyncSession,
    old_snap: Snapshot,
    new_snap: Snapshot,
    system: str,
) -> int:
    """Compare two snapshots. Insert SignalChange rows for any flips.

    Returns the number of changes detected.
    """
    if not old_snap:
        return 0

    now = datetime.now(tz=timezone.utc)
    count = 0

    for ticker, (new_cls, new_score, name) in new_snap.items():
        old = old_snap.get(ticker)
        if old is None:
            continue
        old_cls, old_score, old_name = old
        if old_cls == new_cls:
            continue

        db.add(SignalChange(
            id=uuid.uuid4(),
            ticker=ticker,
            company_name=name or old_name,
            system=system,
            old_classification=old_cls,
            new_classification=new_cls,
            old_score=old_score,
            new_score=new_score,
            detected_at=now,
        ))
        count += 1

    if count > 0:
        await db.commit()

    return count
