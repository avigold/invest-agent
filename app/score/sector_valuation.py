"""Compute sector valuation percentile stats from PredictionScore data.

Groups all scored companies by GICS sector, then for each sector-specific
metric computes p10/p25/p50/p75/p90 breakpoints. Results are stored in the
sector_valuation_stats table for fast retrieval at API time.
"""
from __future__ import annotations

import logging
import math
import statistics
import uuid
from datetime import date, datetime, timezone
from typing import Callable

from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Company,
    CompanyPriceHistory,
    PredictionModel,
    PredictionScore,
    SectorValuationStats,
)
from app.score.sector_metrics import (
    METRIC_DEFINITIONS,
    SECTOR_METRICS,
    compute_valuation_ratios,
    extract_metric_value,
)
from app.score.versions import SECTOR_VALUATION_CALC_VERSION
from app.screen.common_features import GICS_SECTORS

logger = logging.getLogger(__name__)

# Reverse mapping: sector display name → GICS code
_SECTOR_NAME_TO_GICS: dict[str, str] = {v: k for k, v in GICS_SECTORS.items()}

# Outlier bounds for computed ratios
_PE_MAX = 200.0
_PB_MAX = 100.0


def _quantiles(values: list[float], n: int = 10) -> dict[str, float]:
    """Compute p10/p25/p50/p75/p90 from a list of values."""
    if len(values) < 2:
        v = values[0] if values else 0.0
        return {"p10": v, "p25": v, "p50": v, "p75": v, "p90": v}

    values_sorted = sorted(values)
    # Use statistics.quantiles for proper interpolation
    try:
        deciles = statistics.quantiles(values_sorted, n=10)
        quartiles = statistics.quantiles(values_sorted, n=4)
        return {
            "p10": round(deciles[0], 4),
            "p25": round(quartiles[0], 4),
            "p50": round(statistics.median(values_sorted), 4),
            "p75": round(quartiles[2], 4),
            "p90": round(deciles[8], 4),
        }
    except statistics.StatisticsError:
        v = values_sorted[len(values_sorted) // 2]
        return {"p10": v, "p25": v, "p50": v, "p75": v, "p90": v}


def _filter_outliers(values: list[float], metric_key: str) -> list[float]:
    """Remove outliers for specific metrics."""
    if metric_key == "pe_ratio":
        return [v for v in values if 0 < v <= _PE_MAX]
    if metric_key == "pb_ratio":
        return [v for v in values if 0 < v <= _PB_MAX]
    # For other metrics, remove NaN/inf
    return [v for v in values if math.isfinite(v)]


async def compute_sector_valuation_stats(
    db: AsyncSession,
    as_of: date,
    log_fn: Callable[[str], None] | None = None,
) -> list[SectorValuationStats]:
    """Compute and store sector valuation percentile stats.

    Uses PredictionScore data from the most recent model, grouped by sector.
    Returns the list of created SectorValuationStats rows.
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(f"  {msg}")
        logger.info(msg)

    # Find the most recent model (any user — system-wide stats)
    model_result = await db.execute(
        select(PredictionModel)
        .order_by(PredictionModel.created_at.desc())
        .limit(1)
    )
    model = model_result.scalar_one_or_none()
    if model is None:
        _log("No prediction models found — skipping sector valuation stats")
        return []

    # Load all prediction scores for this model
    scores_result = await db.execute(
        select(PredictionScore).where(PredictionScore.model_id == model.id)
    )
    all_scores = list(scores_result.scalars().all())
    if not all_scores:
        _log("No prediction scores found — skipping sector valuation stats")
        return []

    _log(f"Loaded {len(all_scores)} prediction scores from model {model.model_version}")

    # Build ticker→latest_price lookup from CompanyPriceHistory
    ticker_set = {s.ticker for s in all_scores}
    companies_result = await db.execute(
        select(Company).where(Company.ticker.in_(ticker_set))
    )
    companies = {c.ticker: c for c in companies_result.scalars().all()}

    company_ids = [c.id for c in companies.values()]
    ph_result = await db.execute(
        select(CompanyPriceHistory).where(
            CompanyPriceHistory.company_id.in_(company_ids)
        )
    )
    price_histories = {ph.company_id: ph for ph in ph_result.scalars().all()}

    # Map company_id → ticker for price lookup
    cid_to_ticker = {c.id: c.ticker for c in companies.values()}
    ticker_to_price: dict[str, float | None] = {}
    for cid, ph in price_histories.items():
        ticker = cid_to_ticker.get(cid)
        if ticker and ph.prices:
            last_pt = ph.prices[-1]
            price = last_pt.get("price") or last_pt.get("close")
            ticker_to_price[ticker] = price

    # Group scores by GICS sector
    sector_groups: dict[str, list[PredictionScore]] = {}
    for score in all_scores:
        gics = _SECTOR_NAME_TO_GICS.get(score.sector or "", "")
        if not gics:
            continue
        sector_groups.setdefault(gics, []).append(score)

    # Delete existing stats for this as_of + version
    await db.execute(
        sql_delete(SectorValuationStats).where(
            SectorValuationStats.as_of == as_of,
            SectorValuationStats.calc_version == SECTOR_VALUATION_CALC_VERSION,
        )
    )

    results: list[SectorValuationStats] = []

    for gics_code, scores in sorted(sector_groups.items()):
        sector_name = GICS_SECTORS.get(gics_code, f"Unknown ({gics_code})")
        metric_keys = SECTOR_METRICS.get(gics_code, [])
        if not metric_keys:
            continue

        metrics_data: dict[str, dict] = {}

        for metric_key in metric_keys:
            values: list[float] = []
            for score in scores:
                fv = score.feature_values or {}
                price = ticker_to_price.get(score.ticker)
                val_ratios = compute_valuation_ratios(price, fv)
                val = extract_metric_value(metric_key, fv, val_ratios)
                if val is not None:
                    values.append(val)

            filtered = _filter_outliers(values, metric_key)
            if filtered:
                metrics_data[metric_key] = _quantiles(filtered)

        row = SectorValuationStats(
            id=uuid.uuid4(),
            gics_code=gics_code,
            sector_name=sector_name,
            as_of=as_of,
            calc_version=SECTOR_VALUATION_CALC_VERSION,
            company_count=len(scores),
            metrics=metrics_data,
            created_at=datetime.now(tz=timezone.utc),
        )
        db.add(row)
        results.append(row)
        _log(f"{sector_name} ({gics_code}): {len(scores)} companies, "
             f"{len(metrics_data)} metrics computed")

    await db.flush()
    return results
