"""Prediction model API endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Country, CountryScore, Industry, IndustryScore,
    PredictionModel, PredictionScore, User,
)
from app.db.session import get_db
from app.score.feature_scorer import score_from_features
from app.score.versions import (
    COUNTRY_CALC_VERSION, INDUSTRY_CALC_VERSION,
    RECOMMENDATION_THRESHOLDS, RECOMMENDATION_WEIGHTS,
)

router = APIRouter(prefix="/v1/predictions", tags=["predictions"])


class UpdateModelRequest(PydanticBaseModel):
    nickname: str | None = None
    is_active: bool | None = None


async def _resolve_active_model(
    db: AsyncSession, user_id: uuid.UUID
) -> PredictionModel | None:
    """Return the user's active model, or the most recent one as fallback."""
    result = await db.execute(
        select(PredictionModel)
        .where(PredictionModel.user_id == user_id, PredictionModel.is_active.is_(True))
        .limit(1)
    )
    model = result.scalar_one_or_none()
    if model is not None:
        return model

    # Fallback: most recent
    result = await db.execute(
        select(PredictionModel)
        .where(PredictionModel.user_id == user_id)
        .order_by(desc(PredictionModel.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()

# Reverse lookup: sector display name → 2-digit GICS code
_SECTOR_TO_GICS: dict[str, str] = {
    "Energy": "10", "Materials": "15", "Industrials": "20",
    "Consumer Discretionary": "25", "Consumer Staples": "30",
    "Health Care": "35", "Financials": "40",
    "Information Technology": "45", "Communication Services": "50",
    "Utilities": "55", "Real Estate": "60",
}


async def _load_country_scores(db: AsyncSession) -> dict[str, float]:
    """Load latest country scores as {iso2: overall_score}."""
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


async def _load_industry_scores(db: AsyncSession) -> dict[tuple[str, str], float]:
    """Load latest industry scores as {(gics_code, iso2): overall_score}."""
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


def _classify(
    company_score: float,
    country_iso2: str,
    sector_name: str,
    country_scores: dict[str, float] | None,
    industry_scores: dict[tuple[str, str], float] | None,
) -> str:
    """Compute composite classification from sub-scores."""
    gics = _SECTOR_TO_GICS.get(sector_name, "")
    cs = (country_scores or {}).get(country_iso2, 10.0)
    ind = (industry_scores or {}).get((gics, country_iso2), 10.0)
    w = RECOMMENDATION_WEIGHTS
    composite = w["country"] * cs + w["industry"] * ind + w["company"] * company_score
    if composite > RECOMMENDATION_THRESHOLDS["buy"]:
        return "Buy"
    if composite < RECOMMENDATION_THRESHOLDS["sell"]:
        return "Sell"
    return "Hold"


# Columns needed for bulk list view (excludes heavy JSONB blobs)
_BULK_COLUMNS = [
    PredictionScore.id,
    PredictionScore.ticker,
    PredictionScore.company_name,
    PredictionScore.country,
    PredictionScore.sector,
    PredictionScore.probability,
    PredictionScore.confidence_tier,
    PredictionScore.kelly_fraction,
    PredictionScore.suggested_weight,
    PredictionScore.scored_at,
    PredictionScore.feature_values,
]


def _score_dict_bulk(
    row,
    country_scores: dict[str, float] | None = None,
    industry_scores: dict[tuple[str, str], float] | None = None,
) -> dict:
    """Lightweight serialisation for bulk listings (no contributing_features)."""
    det = score_from_features(row.feature_values or {})
    country_iso2 = row.country or ""
    sector_name = row.sector or ""
    classification = _classify(
        det["company_score"], country_iso2, sector_name,
        country_scores, industry_scores,
    )
    return {
        "id": str(row.id),
        "ticker": row.ticker,
        "company_name": row.company_name,
        "country": country_iso2,
        "sector": sector_name,
        "probability": row.probability,
        "confidence_tier": row.confidence_tier,
        "kelly_fraction": row.kelly_fraction,
        "suggested_weight": row.suggested_weight,
        "scored_at": row.scored_at.isoformat(),
        "deterministic_classification": classification,
    }


def _score_dict(
    s: PredictionScore,
    include_feature_values: bool = False,
    country_scores: dict[str, float] | None = None,
    industry_scores: dict[tuple[str, str], float] | None = None,
) -> dict:
    """Full serialisation for single-ticker detail view."""
    det = score_from_features(s.feature_values or {})
    country_iso2 = s.country or (s.contributing_features or {}).get("country", "")
    sector_name = s.sector or (s.contributing_features or {}).get("sector", "")
    classification = _classify(
        det["company_score"], country_iso2, sector_name,
        country_scores, industry_scores,
    )

    d = {
        "id": str(s.id),
        "ticker": s.ticker,
        "company_name": s.company_name,
        "country": country_iso2,
        "sector": sector_name,
        "probability": s.probability,
        "confidence_tier": s.confidence_tier,
        "kelly_fraction": s.kelly_fraction,
        "suggested_weight": s.suggested_weight,
        "contributing_features": s.contributing_features,
        "scored_at": s.scored_at.isoformat(),
        "deterministic_classification": classification,
    }
    if include_feature_values:
        d["feature_values"] = s.feature_values
    return d


@router.get("/models")
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all trained prediction models for the current user."""
    result = await db.execute(
        select(PredictionModel)
        .where(PredictionModel.user_id == user.id)
        .order_by(desc(PredictionModel.created_at))
        .limit(20)
    )
    rows = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "model_version": m.model_version,
            "nickname": m.nickname,
            "is_active": m.is_active,
            "config": m.config,
            "aggregate_metrics": m.aggregate_metrics,
            "feature_importance": m.feature_importance,
            "backtest_results": {
                k: v for k, v in (m.backtest_results or {}).items()
                if k != "folds"  # Exclude per-fold detail from list view
            },
            "created_at": m.created_at.isoformat(),
            "job_id": str(m.job_id) if m.job_id else None,
        }
        for m in rows
    ]


@router.get("/models/latest/scores")
async def get_latest_model_scores(
    limit: int | None = None,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get prediction scores for the active (or most recent) model."""
    model = await _resolve_active_model(db, user.id)
    if model is None:
        raise HTTPException(status_code=404, detail="No models found")

    # Total count
    count_result = await db.execute(
        select(func.count()).where(PredictionScore.model_id == model.id)
    )
    total = count_result.scalar() or 0

    q = (
        select(*_BULK_COLUMNS)
        .where(PredictionScore.model_id == model.id)
        .order_by(desc(PredictionScore.probability))
        .offset(offset)
    )
    if limit is not None:
        q = q.limit(limit)
    result = await db.execute(q)
    rows = result.all()

    cs = await _load_country_scores(db)
    ins = await _load_industry_scores(db)
    return {
        "model_id": str(model.id),
        "model_version": model.model_version,
        "nickname": model.nickname,
        "is_active": model.is_active,
        "created_at": model.created_at.isoformat(),
        "aggregate_metrics": model.aggregate_metrics,
        "total": total,
        "scores": [_score_dict_bulk(r, country_scores=cs, industry_scores=ins) for r in rows],
    }


@router.get("/models/{model_id}")
async def get_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full model detail including backtest results."""
    result = await db.execute(
        select(PredictionModel).where(
            PredictionModel.id == model_id,
            PredictionModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    return {
        "id": str(model.id),
        "model_version": model.model_version,
        "nickname": model.nickname,
        "is_active": model.is_active,
        "config": model.config,
        "fold_metrics": model.fold_metrics,
        "aggregate_metrics": model.aggregate_metrics,
        "feature_importance": model.feature_importance,
        "backtest_results": model.backtest_results,
        "platt_a": model.platt_a,
        "platt_b": model.platt_b,
        "created_at": model.created_at.isoformat(),
        "job_id": str(model.job_id) if model.job_id else None,
    }


@router.patch("/models/{model_id}")
async def update_model(
    model_id: uuid.UUID,
    body: UpdateModelRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a model's nickname and/or active status."""
    result = await db.execute(
        select(PredictionModel).where(
            PredictionModel.id == model_id,
            PredictionModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    if body.nickname is not None:
        model.nickname = body.nickname.strip() or None

    if body.is_active is True:
        # Deactivate all other models for this user first
        await db.execute(
            update(PredictionModel)
            .where(PredictionModel.user_id == user.id)
            .values(is_active=False)
        )
        model.is_active = True
    elif body.is_active is False:
        model.is_active = False

    await db.commit()
    await db.refresh(model)

    return {
        "id": str(model.id),
        "model_version": model.model_version,
        "nickname": model.nickname,
        "is_active": model.is_active,
        "created_at": model.created_at.isoformat(),
    }


@router.get("/models/{model_id}/scores")
async def get_model_scores(
    model_id: uuid.UUID,
    limit: int | None = None,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get prediction scores for a model."""
    from sqlalchemy import func

    # Verify model exists and belongs to user
    result = await db.execute(
        select(PredictionModel.id).where(
            PredictionModel.id == model_id,
            PredictionModel.user_id == user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Model not found")

    # Total count
    count_result = await db.execute(
        select(func.count()).where(PredictionScore.model_id == model_id)
    )
    total = count_result.scalar() or 0

    q = (
        select(*_BULK_COLUMNS)
        .where(PredictionScore.model_id == model_id)
        .order_by(desc(PredictionScore.probability))
        .offset(offset)
    )
    if limit is not None:
        q = q.limit(limit)
    result = await db.execute(q)
    rows = result.all()

    cs = await _load_country_scores(db)
    ins = await _load_industry_scores(db)
    return {
        "items": [_score_dict_bulk(r, country_scores=cs, industry_scores=ins) for r in rows],
        "total": total,
    }


@router.get("/score/{ticker}")
async def get_score_for_ticker(
    ticker: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full ML score detail for a single ticker, including feature values
    and full composite deterministic scores."""
    ticker = ticker.replace("-", ".").upper()

    # Find active (or most recent) model for user
    model = await _resolve_active_model(db, user.id)
    if model is None:
        raise HTTPException(status_code=404, detail="No models found")

    # Find score for this ticker
    result = await db.execute(
        select(PredictionScore).where(
            PredictionScore.model_id == model.id,
            PredictionScore.ticker == ticker,
        )
    )
    score = result.scalar_one_or_none()
    if score is None:
        raise HTTPException(status_code=404, detail=f"No ML score found for '{ticker}'")

    # Pre-load country/industry scores for composite
    cs_lookup = await _load_country_scores(db)
    ins_lookup = await _load_industry_scores(db)

    # Build response with full feature values
    d = _score_dict(
        score, include_feature_values=True,
        country_scores=cs_lookup, industry_scores=ins_lookup,
    )
    d["model_id"] = str(model.id)
    d["model_version"] = model.model_version

    # Full composite fundamentals breakdown
    det = score_from_features(score.feature_values or {})
    country_iso2 = score.country or ""
    gics = _SECTOR_TO_GICS.get(score.sector or "", "")
    cs_val = cs_lookup.get(country_iso2, 10.0)
    ind_val = ins_lookup.get((gics, country_iso2), 10.0)
    w = RECOMMENDATION_WEIGHTS
    composite = round(
        w["country"] * cs_val + w["industry"] * ind_val
        + w["company"] * det["company_score"], 2
    )

    d["fundamentals"] = {
        "classification": d["deterministic_classification"],
        "composite_score": composite,
        "company_score": det["company_score"],
        "fundamental_score": det["fundamental_score"],
        "market_score": det["market_score"],
        "country_score": cs_val,
        "industry_score": ind_val,
    }
    return d


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a prediction model and its scores."""
    result = await db.execute(
        select(PredictionModel).where(
            PredictionModel.id == model_id,
            PredictionModel.user_id == user.id,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    await db.delete(model)
    await db.commit()
