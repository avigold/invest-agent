"""Seed the data_sources table with known sources."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataSource

_SOURCES = [
    {"name": "world_bank", "base_url": "https://api.worldbank.org/v2/", "requires_auth": False},
    {"name": "fred", "base_url": "https://api.stlouisfed.org/fred/", "requires_auth": True},
    {"name": "yfinance", "base_url": "", "requires_auth": False},
    {"name": "gdelt", "base_url": "", "requires_auth": False},
    {"name": "imf", "base_url": "https://www.imf.org/external/datamapper/api/v1/", "requires_auth": False},
]


async def seed_data_sources(db: AsyncSession) -> dict[str, DataSource]:
    """Upsert the known data sources. Returns {name: DataSource}."""
    sources: dict[str, DataSource] = {}
    for src in _SOURCES:
        result = await db.execute(
            select(DataSource).where(DataSource.name == src["name"])
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            ds = DataSource(**src)
            db.add(ds)
            await db.flush()
            sources[ds.name] = ds
        else:
            sources[existing.name] = existing
    return sources
