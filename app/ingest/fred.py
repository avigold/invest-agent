"""FRED API ingest."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CountrySeries, CountrySeriesPoint, Country, DataSource
from app.ingest.artefact_store import ArtefactStore

_BASE_URL = "https://api.stlouisfed.org/fred"


async def fetch_fred_series(
    client: httpx.AsyncClient,
    series_id: str,
    api_key: str,
    start_date: str,
    end_date: str,
) -> tuple[list[dict], str]:
    """Fetch series observations from FRED API.

    Returns (parsed observations, raw response text).
    """
    url = f"{_BASE_URL}/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date,
    }
    resp = await client.get(url, params=params, timeout=30)
    resp.raise_for_status()
    raw = resp.text
    data = resp.json()

    observations = []
    for obs in data.get("observations", []):
        if obs.get("value") not in (None, "", "."):
            try:
                observations.append({
                    "date": obs["date"],
                    "value": float(obs["value"]),
                })
            except (ValueError, KeyError):
                continue
    return observations, raw


async def ingest_fred_for_country(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    fred_source: DataSource,
    country: Country,
    fred_series: dict[str, dict],
    api_key: str,
    start_date: str,
    end_date: str,
    log_fn: Callable[[str], None],
) -> list[uuid.UUID]:
    """Fetch FRED series, store artefacts + points.

    Args:
        fred_series: mapping of series_key -> {"series_id": "FEDFUNDS", "name": ..., "unit": ..., "frequency": ...}

    Skips entirely if api_key is empty.
    Returns list of artefact IDs.
    """
    if not api_key:
        log_fn(f"  FRED: Skipping (no API key configured)")
        return []

    artefact_ids: list[uuid.UUID] = []

    async with httpx.AsyncClient() as client:
        for series_key, meta in fred_series.items():
            series_id = meta["series_id"]
            log_fn(f"  FRED: {series_id} ({meta['name']})")

            try:
                observations, raw_text = await fetch_fred_series(
                    client, series_id, api_key, start_date, end_date,
                )
            except httpx.HTTPError as e:
                log_fn(f"    WARN: Failed to fetch {series_id}: {e}")
                continue

            if not observations:
                log_fn(f"    No data for {series_id}")
                continue

            # Store artefact
            artefact = await artefact_store.store(
                db=db,
                data_source_id=fred_source.id,
                source_url=f"{_BASE_URL}/series/observations?series_id={series_id}",
                fetch_params={"series_id": series_id, "start": start_date, "end": end_date},
                content=raw_text,
                time_window_start=datetime.strptime(start_date, "%Y-%m-%d").date(),
                time_window_end=datetime.strptime(end_date, "%Y-%m-%d").date(),
            )
            artefact_ids.append(artefact.id)

            # FRED data is applied to all countries (global risk proxy)
            series_name = f"fred_{series_key}"
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
                    source="fred",
                    indicator_code=series_id,
                    unit=meta.get("unit", ""),
                    frequency=meta.get("frequency", "daily"),
                )
                db.add(series)
                await db.flush()

            # Upsert points
            for obs in observations:
                obs_date = datetime.strptime(obs["date"], "%Y-%m-%d").date()
                stmt = pg_insert(CountrySeriesPoint).values(
                    id=uuid.uuid4(),
                    series_id=series.id,
                    artefact_id=artefact.id,
                    date=obs_date,
                    value=obs["value"],
                ).on_conflict_do_update(
                    constraint="uq_series_point_date",
                    set_={"value": obs["value"], "artefact_id": artefact.id},
                )
                await db.execute(stmt)

            log_fn(f"    Stored {len(observations)} observations")

    return artefact_ids
