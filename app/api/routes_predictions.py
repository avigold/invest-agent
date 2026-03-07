"""Prediction model API endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sql_delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import PredictionModel, PredictionScore, User
from app.db.session import get_db

router = APIRouter(prefix="/v1/predictions", tags=["predictions"])


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


@router.get("/models/{model_id}/scores")
async def get_model_scores(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get prediction scores for a model."""
    # Verify model exists and belongs to user
    result = await db.execute(
        select(PredictionModel.id).where(
            PredictionModel.id == model_id,
            PredictionModel.user_id == user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Model not found")

    result = await db.execute(
        select(PredictionScore)
        .where(PredictionScore.model_id == model_id)
        .order_by(desc(PredictionScore.probability))
    )
    scores = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "ticker": s.ticker,
            "company_name": s.company_name,
            "probability": s.probability,
            "confidence_tier": s.confidence_tier,
            "kelly_fraction": s.kelly_fraction,
            "suggested_weight": s.suggested_weight,
            "contributing_features": s.contributing_features,
            "feature_values": s.feature_values,
            "scored_at": s.scored_at.isoformat(),
        }
        for s in scores
    ]


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
