"""Live screener API: real-time filtering + saved screen configs.

Uses SQL-level JSONB filtering for performance — pushes filters and
sorting to PostgreSQL rather than loading all rows into Python.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import Float, asc, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Company, CompanyPriceHistory, PredictionModel, PredictionScore,
    SavedScreen, User,
)
from app.db.session import get_db
from app.screen.live_filter import (
    DEFAULT_COLUMNS, FIELD_DEFINITIONS, TEMPLATES,
    apply_filters, build_enriched_row, rows_to_csv,
    _FIELD_MAP,
)

router = APIRouter(prefix="/v1/screener", tags=["screener"])


# ── Request / response models ────────────────────────────────────────────

class FilterRule(PydanticBaseModel):
    field: str
    op: str
    value: Any


class FilterSet(PydanticBaseModel):
    rules: list[FilterRule] = []


class ScreenRequest(PydanticBaseModel):
    filters: FilterSet = FilterSet()
    sort_by: str = "probability"
    sort_desc: bool = True
    limit: int = 200
    offset: int = 0


class SaveScreenRequest(PydanticBaseModel):
    name: str
    description: str | None = None
    filters: FilterSet = FilterSet()
    sort_by: str | None = None
    sort_desc: bool = True
    columns: list[str] | None = None


# ── SQL field mapping ────────────────────────────────────────────────────

# Fields that map directly to PredictionScore columns
_DIRECT_COLUMNS: dict[str, Any] = {
    "country": PredictionScore.country,
    "sector": PredictionScore.sector,
    "probability": PredictionScore.probability,
    "ml_classification": PredictionScore.confidence_tier,
}

# Fields that map to feature_values JSONB keys
_JSONB_FIELDS: dict[str, str] = {
    "roe": "roe",
    "roa": "roa",
    "net_margin": "net_margin",
    "gross_margin": "gross_margin",
    "operating_margin": "operating_margin",
    "revenue_growth": "revenue_growth",
    "eps_growth": "eps_growth",
    "debt_equity": "debt_equity",
    "current_ratio": "current_ratio",
    "interest_coverage": "interest_coverage",
    "momentum_12m": "momentum_12m",
    "max_dd_12m": "max_dd_12m",
    "dividend_yield": "dividend_payout",
    "fcf_yield": "fcf_yield",
}

# Fields that require Python computation (can't push to SQL)
_COMPUTED_FIELDS = {
    "pe_ratio", "pb_ratio", "fundamental_score", "market_score",
    "company_score", "det_classification",
}


def _field_sql_expr(field_key: str):
    """Convert a filter field name to a SQLAlchemy column expression, or None."""
    if field_key in _DIRECT_COLUMNS:
        return _DIRECT_COLUMNS[field_key]
    if field_key in _JSONB_FIELDS:
        fv_key = _JSONB_FIELDS[field_key]
        fd = _FIELD_MAP.get(field_key, {})
        if fd.get("type") == "numeric":
            return cast(PredictionScore.feature_values[fv_key].astext, Float)
        return PredictionScore.feature_values[fv_key].astext
    return None


def _rule_to_sql(rule: FilterRule):
    """Convert a filter rule to a SQLAlchemy WHERE clause, or None if computed."""
    expr = _field_sql_expr(rule.field)
    if expr is None:
        return None

    v = rule.value
    op = rule.op

    if op == "gt":
        return expr > float(v)
    if op == "gte":
        return expr >= float(v)
    if op == "lt":
        return expr < float(v)
    if op == "lte":
        return expr <= float(v)
    if op == "eq":
        return expr == str(v)
    if op == "between":
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return expr.between(float(v[0]), float(v[1]))
        return None
    if op == "in":
        if isinstance(v, (list, tuple)):
            return expr.in_([str(x) for x in v])
        return None
    if op == "not_in":
        if isinstance(v, (list, tuple)):
            return ~expr.in_([str(x) for x in v])
        return None

    return None


def _sort_sql_expr(sort_by: str, sort_desc: bool):
    """Build a SQLAlchemy ORDER BY expression, or None if computed field."""
    expr = _field_sql_expr(sort_by)
    if expr is None:
        return None
    return desc(expr).nullslast() if sort_desc else asc(expr).nullslast()


# ── Helpers ──────────────────────────────────────────────────────────────

async def _resolve_active_model(
    db: AsyncSession, user_id: uuid.UUID,
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
    result = await db.execute(
        select(PredictionModel)
        .where(PredictionModel.user_id == user_id)
        .order_by(desc(PredictionModel.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _enrich_scores(
    db: AsyncSession, scores: list[PredictionScore],
) -> list[dict[str, Any]]:
    """Build enriched row dicts for a (small) list of PredictionScore rows.

    Loads latest prices only for the given tickers — safe for page-sized sets.
    """
    if not scores:
        return []

    ticker_list = [s.ticker for s in scores]

    # Get company IDs for price lookup
    company_result = await db.execute(
        select(Company.id, Company.ticker).where(Company.ticker.in_(ticker_list))
    )
    company_map = {row.ticker: row.id for row in company_result}

    # Get latest prices
    price_map: dict[str, float | None] = {}
    company_ids = list(company_map.values())
    if company_ids:
        ph_result = await db.execute(
            select(CompanyPriceHistory.company_id, CompanyPriceHistory.prices)
            .where(CompanyPriceHistory.company_id.in_(company_ids))
        )
        cid_to_ticker = {cid: t for t, cid in company_map.items()}
        for row in ph_result:
            if row.prices:
                last_pt = row.prices[-1]
                price = last_pt.get("price") or last_pt.get("close")
                ticker = cid_to_ticker.get(row.company_id)
                if ticker and price:
                    price_map[ticker] = price

    return [
        build_enriched_row(s, price_map.get(s.ticker))
        for s in scores
    ]


def _sort_rows(
    rows: list[dict[str, Any]], sort_by: str, sort_desc: bool,
) -> list[dict[str, Any]]:
    """Sort rows by a field, handling None values."""
    def sort_key(row: dict) -> tuple:
        val = row.get(sort_by)
        if val is None:
            return (1, 0)
        if isinstance(val, str):
            return (0, val.lower())
        return (0, val)

    return sorted(rows, key=sort_key, reverse=sort_desc)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("/live/fields")
async def get_fields(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return field metadata for the filter builder UI."""
    fields = [dict(fd) for fd in FIELD_DEFINITIONS]

    model = await _resolve_active_model(db, user.id)
    if model:
        countries_result = await db.execute(
            select(PredictionScore.country)
            .where(PredictionScore.model_id == model.id)
            .distinct()
        )
        sectors_result = await db.execute(
            select(PredictionScore.sector)
            .where(PredictionScore.model_id == model.id)
            .distinct()
        )
        country_vals = sorted([r[0] for r in countries_result if r[0]])
        sector_vals = sorted([r[0] for r in sectors_result if r[0]])

        for f in fields:
            if f["key"] == "country":
                f["values"] = country_vals
            elif f["key"] == "sector":
                f["values"] = sector_vals

    return {"fields": fields}


@router.post("/live/screen")
async def live_screen(
    req: ScreenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Filter the current universe on financial metrics.

    Uses a two-path strategy:
    - Fast path: all filters and sort are SQL-pushable -> filter, sort, paginate in SQL.
    - Slow path: computed-field filters or sort -> load SQL-filtered subset into Python.
    """
    model = await _resolve_active_model(db, user.id)
    if model is None:
        return {"total": 0, "items": []}

    # Base query: all scores for the active model
    base = select(PredictionScore).where(PredictionScore.model_id == model.id)

    # Partition rules into SQL-pushable vs computed
    sql_clauses = []
    computed_rules = []
    for rule in req.filters.rules:
        clause = _rule_to_sql(rule)
        if clause is not None:
            sql_clauses.append(clause)
        elif rule.field in _COMPUTED_FIELDS:
            computed_rules.append(rule.model_dump())

    # Apply SQL-level filters
    for clause in sql_clauses:
        base = base.where(clause)

    sort_expr = _sort_sql_expr(req.sort_by, req.sort_desc)
    needs_python = bool(computed_rules) or sort_expr is None

    if not needs_python:
        # ── Fast path: everything in SQL ──────────────────────────────
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        page_q = base.order_by(sort_expr).offset(req.offset).limit(req.limit)
        page_scores = (await db.execute(page_q)).scalars().all()

        items = await _enrich_scores(db, page_scores)
        return {"total": total, "items": items}
    else:
        # ── Slow path: load SQL-filtered subset, compute in Python ────
        # Safety cap: if SQL filtering still yields too many rows, limit
        capped = base.limit(5000)
        result = await db.execute(capped)
        scores = result.scalars().all()

        enriched = await _enrich_scores(db, scores)

        if computed_rules:
            enriched = apply_filters(enriched, computed_rules)

        total = len(enriched)
        sorted_rows = _sort_rows(enriched, req.sort_by, req.sort_desc)
        page = sorted_rows[req.offset: req.offset + req.limit]
        return {"total": total, "items": page}


@router.post("/live/export")
async def live_export(
    req: ScreenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export filtered results as CSV."""
    model = await _resolve_active_model(db, user.id)
    if model is None:
        return Response(content="", media_type="text/csv")

    base = select(PredictionScore).where(PredictionScore.model_id == model.id)

    for rule in req.filters.rules:
        clause = _rule_to_sql(rule)
        if clause is not None:
            base = base.where(clause)

    # Cap export at 5000 rows
    sort_expr = _sort_sql_expr(req.sort_by, req.sort_desc)
    if sort_expr is not None:
        base = base.order_by(sort_expr)
    base = base.limit(5000)

    result = await db.execute(base)
    scores = result.scalars().all()
    enriched = await _enrich_scores(db, scores)

    # Apply any computed filters in Python
    computed_rules = [
        r.model_dump() for r in req.filters.rules
        if r.field in _COMPUTED_FIELDS
    ]
    if computed_rules:
        enriched = apply_filters(enriched, computed_rules)

    if sort_expr is None:
        enriched = _sort_rows(enriched, req.sort_by, req.sort_desc)

    csv_data = rows_to_csv(enriched)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=screen_results.csv"},
    )


# ── Saved screens ────────────────────────────────────────────────────────

@router.get("/saved")
async def list_saved_screens(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's saved screens plus pre-built templates."""
    result = await db.execute(
        select(SavedScreen)
        .where(SavedScreen.user_id == user.id)
        .order_by(desc(SavedScreen.updated_at))
    )
    saved = result.scalars().all()

    items: list[dict] = []
    for tpl in TEMPLATES:
        items.append(tpl)
    for s in saved:
        items.append({
            "id": str(s.id),
            "name": s.name,
            "description": s.description,
            "is_template": False,
            "filters": s.filters,
            "sort_by": s.sort_by,
            "sort_desc": s.sort_desc,
            "columns": s.columns,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        })

    return {"items": items}


@router.post("/saved", status_code=201)
async def save_screen(
    req: SaveScreenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a new screener configuration."""
    screen = SavedScreen(
        user_id=user.id,
        name=req.name,
        description=req.description,
        filters=req.filters.model_dump(),
        sort_by=req.sort_by,
        sort_desc=req.sort_desc,
        columns=req.columns,
    )
    db.add(screen)
    await db.commit()
    await db.refresh(screen)

    return {
        "id": str(screen.id),
        "name": screen.name,
        "description": screen.description,
        "filters": screen.filters,
        "sort_by": screen.sort_by,
        "sort_desc": screen.sort_desc,
        "columns": screen.columns,
        "created_at": screen.created_at.isoformat(),
    }


@router.put("/saved/{screen_id}")
async def update_saved_screen(
    screen_id: uuid.UUID,
    req: SaveScreenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a saved screener configuration."""
    result = await db.execute(
        select(SavedScreen).where(
            SavedScreen.id == screen_id, SavedScreen.user_id == user.id
        )
    )
    screen = result.scalar_one_or_none()
    if not screen:
        raise HTTPException(status_code=404, detail="Saved screen not found")

    screen.name = req.name
    screen.description = req.description
    screen.filters = req.filters.model_dump()
    screen.sort_by = req.sort_by
    screen.sort_desc = req.sort_desc
    screen.columns = req.columns
    await db.commit()
    await db.refresh(screen)

    return {"id": str(screen.id), "name": screen.name, "filters": screen.filters}


@router.delete("/saved/{screen_id}", status_code=204)
async def delete_saved_screen(
    screen_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a saved screener configuration."""
    result = await db.execute(
        select(SavedScreen).where(
            SavedScreen.id == screen_id, SavedScreen.user_id == user.id
        )
    )
    screen = result.scalar_one_or_none()
    if not screen:
        raise HTTPException(status_code=404, detail="Saved screen not found")

    await db.delete(screen)
    await db.commit()
