"""World Bank Indicators API ingest."""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artefact, Country, CountrySeries, CountrySeriesPoint, DataSource
from app.ingest.artefact_store import ArtefactStore

_BASE_URL = "https://api.worldbank.org/v2"


async def fetch_world_bank_indicator(
    client: httpx.AsyncClient,
    iso2: str,
    indicator: str,
    start_year: int,
    end_year: int,
) -> tuple[list[dict], str]:
    """Fetch indicator data from World Bank API.

    Returns (parsed data points, raw response text).
    """
    url = f"{_BASE_URL}/country/{iso2}/indicator/{indicator}"
    params = {"date": f"{start_year}:{end_year}", "format": "json", "per_page": "500"}
    resp = await client.get(url, params=params, timeout=30)
    resp.raise_for_status()
    raw = resp.text
    data = resp.json()

    # World Bank returns [metadata, data_array]
    if not isinstance(data, list) or len(data) < 2 or data[1] is None:
        return [], raw

    points = []
    for item in data[1]:
        if item.get("value") is not None:
            points.append({"date": str(item["date"]), "value": float(item["value"])})
    return points, raw


async def ingest_world_bank_for_country(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    wb_source: DataSource,
    country: Country,
    indicators: dict[str, str],
    start_year: int,
    end_year: int,
    log_fn: Callable[[str], None],
) -> list[uuid.UUID]:
    """Fetch all WB indicators for a country, store artefacts + series points.

    Args:
        indicators: mapping of series_name -> indicator_code,
            e.g. {"gdp_growth": "NY.GDP.MKTP.KD.ZG"}

    Returns list of artefact IDs created.
    """
    artefact_ids: list[uuid.UUID] = []

    async with httpx.AsyncClient() as client:
        for series_name, indicator_code in indicators.items():
            log_fn(f"  World Bank: {country.iso2} / {series_name} ({indicator_code})")

            try:
                points, raw_text = await fetch_world_bank_indicator(
                    client, country.iso2, indicator_code, start_year, end_year,
                )
            except httpx.HTTPError as e:
                log_fn(f"    WARN: Failed to fetch {indicator_code} for {country.iso2}: {e}")
                continue

            if not points:
                log_fn(f"    No data for {indicator_code}")
                continue

            # Store artefact
            artefact = await artefact_store.store(
                db=db,
                data_source_id=wb_source.id,
                source_url=f"{_BASE_URL}/country/{country.iso2}/indicator/{indicator_code}",
                fetch_params={
                    "iso2": country.iso2,
                    "indicator": indicator_code,
                    "start_year": start_year,
                    "end_year": end_year,
                },
                content=raw_text,
                time_window_start=date(start_year, 1, 1),
                time_window_end=date(end_year, 12, 31),
            )
            artefact_ids.append(artefact.id)

            # Upsert series
            result = await db.execute(
                select(CountrySeries).where(
                    CountrySeries.country_id == country.id,
                    CountrySeries.series_name == series_name,
                )
            )
            series = result.scalar_one_or_none()
            if series is None:
                series = CountrySeries(
                    country_id=country.id,
                    series_name=series_name,
                    source="world_bank",
                    indicator_code=indicator_code,
                    unit="percent" if "ZG" in indicator_code or "ZS" in indicator_code or "GD.ZS" in indicator_code else "usd",
                    frequency="annual",
                )
                db.add(series)
                await db.flush()

            # Upsert points
            for pt in points:
                yr = int(pt["date"])
                stmt = pg_insert(CountrySeriesPoint).values(
                    id=uuid.uuid4(),
                    series_id=series.id,
                    artefact_id=artefact.id,
                    date=date(yr, 1, 1),
                    value=pt["value"],
                ).on_conflict_do_update(
                    constraint="uq_series_point_date",
                    set_={"value": pt["value"], "artefact_id": artefact.id},
                )
                await db.execute(stmt)

            log_fn(f"    Stored {len(points)} points")

    return artefact_ids
