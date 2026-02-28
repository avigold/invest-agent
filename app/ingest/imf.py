"""IMF World Economic Outlook (WEO) data ingest via DataMapper API."""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Country, CountrySeries, CountrySeriesPoint, DataSource
from app.ingest.artefact_store import ArtefactStore

_BASE_URL = "https://www.imf.org/external/datamapper/api/v1"

# IMF DataMapper uses ISO 3166-1 alpha-3 country codes.
_ISO2_TO_ISO3: dict[str, str] = {
    "US": "USA",
    "GB": "GBR",
    "CA": "CAN",
    "AU": "AUS",
    "JP": "JPN",
    "DE": "DEU",
    "FR": "FRA",
    "NL": "NLD",
    "CH": "CHE",
    "SE": "SWE",
}


async def fetch_imf_indicator(
    client: httpx.AsyncClient,
    iso3: str,
    indicator: str,
    start_year: int,
    end_year: int,
) -> tuple[list[dict], str]:
    """Fetch indicator data from IMF DataMapper API.

    Returns (parsed data points, raw response text).
    Each point: {"date": "2024", "value": 236.1}
    """
    periods = ",".join(str(y) for y in range(start_year, end_year + 1))
    url = f"{_BASE_URL}/{indicator}/{iso3}"
    resp = await client.get(url, params={"periods": periods}, timeout=30)
    resp.raise_for_status()
    raw = resp.text
    data = resp.json()

    # IMF response: {"values": {"GGXWDG_NGDP": {"JPN": {"2020": 258.4, ...}}}}
    values_block = data.get("values", {}).get(indicator, {}).get(iso3, {})

    points = []
    for year_str, value in sorted(values_block.items()):
        if value is not None:
            points.append({"date": year_str, "value": round(float(value), 1)})

    return points, raw


async def ingest_imf_for_country(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    imf_source: DataSource,
    country: Country,
    indicators: dict[str, str],
    start_year: int,
    end_year: int,
    log_fn: Callable[[str], None],
) -> list[uuid.UUID]:
    """Fetch IMF WEO indicators for a country, store artefacts + series points.

    Args:
        indicators: mapping of series_name -> IMF indicator code,
            e.g. {"govt_debt_gdp": "GGXWDG_NGDP"}

    Returns list of artefact IDs created.
    """
    iso3 = _ISO2_TO_ISO3.get(country.iso2)
    if iso3 is None:
        log_fn(f"  IMF: No ISO3 mapping for {country.iso2}, skipping")
        return []

    artefact_ids: list[uuid.UUID] = []

    async with httpx.AsyncClient() as client:
        for series_name, indicator_code in indicators.items():
            log_fn(f"  IMF: {country.iso2} / {series_name} ({indicator_code})")

            try:
                points, raw_text = await fetch_imf_indicator(
                    client, iso3, indicator_code, start_year, end_year,
                )
            except httpx.HTTPError as e:
                log_fn(f"    WARN: Failed to fetch {indicator_code} for {country.iso2}: {e}")
                continue

            if not points:
                log_fn(f"    No data for {indicator_code}")
                continue

            # Store artefact
            source_url = f"{_BASE_URL}/{indicator_code}/{iso3}"
            artefact = await artefact_store.store(
                db=db,
                data_source_id=imf_source.id,
                source_url=source_url,
                fetch_params={
                    "iso2": country.iso2,
                    "iso3": iso3,
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
                    source="imf",
                    indicator_code=indicator_code,
                    unit="percent",
                    frequency="annual",
                )
                db.add(series)
                await db.flush()
            else:
                # Update source metadata if previously from a different source
                series.source = "imf"
                series.indicator_code = indicator_code

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
