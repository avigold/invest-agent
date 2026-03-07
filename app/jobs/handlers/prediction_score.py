"""Handler for prediction_score job command.

Re-scores the current universe using an existing trained model.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PredictionModel, PredictionScore
from app.predict.model import TrainedModel
from app.predict.scorer import score_current_universe
from app.predict.strategy import build_portfolio

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def prediction_score_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Re-score current universe using an existing model."""
    model_id = job.params.get("model_id", "")
    if not model_id:
        _log(job, "ERROR: 'model_id' param is required")
        job.status = "failed"
        return

    _log(job, f"=== Re-scoring Universe ===")
    _log(job, f"Model ID: {model_id}")

    async with session_factory() as db:
        # Load model
        result = await db.execute(
            select(PredictionModel).where(
                PredictionModel.id == uuid.UUID(model_id),
                PredictionModel.user_id == job.user_id,
            )
        )
        pred_model = result.scalar_one_or_none()
        if pred_model is None:
            _log(job, "ERROR: Model not found or access denied")
            job.status = "failed"
            return

        if not pred_model.model_blob:
            _log(job, "ERROR: Model has no stored blob")
            job.status = "failed"
            return

        # Deserialize model
        _log(job, "Loading trained model...")
        model = TrainedModel.deserialize(
            pred_model.model_blob,
            feature_importance=pred_model.feature_importance,
            train_config=pred_model.config,
        )

        # Score current universe
        _log(job, "\n--- Scoring current universe ---")
        scored = await score_current_universe(
            db, model,
            log_fn=lambda msg: _log(job, msg),
        )

        # Build portfolio
        pred_dicts = [
            {"ticker": s.ticker, "probability": s.probability, "sector": "Unknown"}
            for s in scored
        ]
        portfolio = build_portfolio(pred_dicts)
        weight_map = {p.ticker: p.weight for p in portfolio}

        # Delete old scores for this model
        await db.execute(
            sql_delete(PredictionScore).where(
                PredictionScore.model_id == pred_model.id
            )
        )

        # Store new scores
        for s in scored:
            w = weight_map.get(s.ticker, 0)
            ps = PredictionScore(
                model_id=pred_model.id,
                user_id=job.user_id,
                ticker=s.ticker,
                company_name=s.company_name,
                probability=s.probability,
                confidence_tier=s.confidence,
                kelly_fraction=s.kelly,
                suggested_weight=round(w, 4),
                contributing_features=s.contributing_features,
                feature_values=s.feature_values,
                job_id=job.id,
            )
            db.add(ps)

        await db.commit()

        _log(job, f"\nScores updated: {len(scored)} companies")
        _log(job, f"Top: {scored[0].ticker} (p={scored[0].probability:.3f})" if scored else "")
        _log(job, "Done.")
