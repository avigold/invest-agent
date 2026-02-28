"""GDELT political stability ingest via DOC 2.0 API.

Fetches instability-themed article volume per country from the GDELT DOC API,
computes a monthly average, and inverts it to a 0-1 stability value.

Themes queried: PROTEST, ARMEDCONFLICT, TERROR, POLITICAL_TURMOIL.
The "Volume Intensity" metric is already normalized by total global article
volume, so values are directly comparable across countries and time.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import uuid
from datetime import date
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Country, CountrySeries, CountrySeriesPoint, DataSource
from app.ingest.artefact_store import ArtefactStore

logger = logging.getLogger(__name__)

_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

_INSTABILITY_QUERY = (
    "sourcecountry:{fips} "
    "(theme:PROTEST OR theme:ARMEDCONFLICT OR theme:TERROR OR theme:POLITICAL_TURMOIL)"
)

_FALLBACK_VALUE = 0.5

# GDELT DOC API uses FIPS 10-4 country codes for sourcecountry filter.
# These differ from ISO 3166-1 alpha-2 for some countries.
_ISO2_TO_FIPS: dict[str, str] = {
    "US": "US",
    "GB": "UK",
    "CA": "CA",
    "AU": "AS",
    "JP": "JA",
    "DE": "GM",
    "FR": "FR",
    "NL": "NL",
    "CH": "SZ",
    "SE": "SW",
}


def _parse_csv_and_average(csv_text: str, target_month: date) -> float | None:
    """Parse GDELT DOC timeline CSV and return mean value for the target month.

    CSV format: Date,Series,Value (may have BOM prefix)
    Returns None if no data points match the target month.
    """
    # Strip BOM that GDELT sometimes includes
    clean = csv_text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(clean))
    values: list[float] = []

    for row in reader:
        try:
            row_date = date.fromisoformat(row["Date"])
            if row_date.year == target_month.year and row_date.month == target_month.month:
                values.append(float(row["Value"]))
        except (KeyError, ValueError):
            continue

    if not values:
        return None

    return sum(values) / len(values)


async def _fetch_gdelt_csv(client: httpx.AsyncClient, fips_code: str) -> str:
    """Fetch instability timeline CSV from GDELT DOC API.

    Uses params= for proper URL encoding of the query with parentheses.
    """
    query = _INSTABILITY_QUERY.format(fips=fips_code)
    resp = await client.get(
        _DOC_API_URL,
        params={
            "query": query,
            "mode": "timelinevol",
            "format": "csv",
            "TIMESPAN": "3m",
        },
    )
    resp.raise_for_status()
    return resp.text


async def ingest_gdelt_stability(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    gdelt_source: DataSource,
    country: Country,
    as_of: date,
    log_fn: Callable[[str], None],
) -> list[uuid.UUID]:
    """Fetch instability data from GDELT DOC API, compute stability score.

    stability_value = 1.0 - normalized_instability, clamped to [0, 1].
    Falls back to 0.5 if the API is unreachable or returns no data.
    """
    fips = _ISO2_TO_FIPS.get(country.iso2, country.iso2)

    csv_text: str | None = None
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            # Retry up to 2 times — GDELT API is slow and intermittent
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    csv_text = await _fetch_gdelt_csv(client, fips)
                    break
                except Exception as e:
                    last_err = e
                    if attempt < 2:
                        log_fn(f"  GDELT: {country.iso2} — attempt {attempt + 1} failed ({e}), retrying...")
                        await asyncio.sleep(5)
            else:
                raise last_err  # type: ignore[misc]
    except Exception as e:
        log_fn(f"  GDELT: {country.iso2} — API error: {e}, using fallback")
        logger.warning("GDELT fetch failed for %s: %s", country.iso2, e)

    if csv_text and csv_text.lstrip("\ufeff").startswith("Date"):
        monthly_instability = _parse_csv_and_average(csv_text, as_of)
    else:
        # Got HTML or garbage instead of CSV
        if csv_text:
            log_fn(f"  GDELT: {country.iso2} — got non-CSV response, using fallback")
        monthly_instability = None

    if monthly_instability is not None:
        # Instability is a volume percentage (typically 0-10 range).
        # Normalize to 0-1 by dividing by a reasonable cap, then invert.
        cap = 10.0
        normalized = min(monthly_instability / cap, 1.0)
        stability_value = max(1.0 - normalized, 0.0)
        log_fn(
            f"  GDELT stability: {country.iso2} = {stability_value:.3f}"
            f" (instability_vol={monthly_instability:.3f})"
        )
    else:
        stability_value = _FALLBACK_VALUE
        log_fn(f"  GDELT stability: {country.iso2} = {stability_value} (fallback, no data)")

    # Build source URL for evidence chain (human-readable)
    source_url = f"{_DOC_API_URL}?query={_INSTABILITY_QUERY.format(fips=fips)}&mode=timelinevol&format=csv&TIMESPAN=3m"

    # Store the raw response as artefact
    artefact_content = csv_text if csv_text else json.dumps({
        "fallback": True,
        "iso2": country.iso2,
        "value": stability_value,
    })

    artefact = await artefact_store.store(
        db=db,
        data_source_id=gdelt_source.id,
        source_url=source_url,
        fetch_params={"iso2": country.iso2, "fips": fips, "as_of": str(as_of)},
        content=artefact_content,
        time_window_start=as_of.replace(day=1),
        time_window_end=as_of,
    )

    # Upsert series
    series_name = "stability"
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
            source="gdelt",
            indicator_code="stability_index",
            unit="index",
            frequency="monthly",
        )
        db.add(series)
        await db.flush()

    # Upsert point
    stmt = pg_insert(CountrySeriesPoint).values(
        id=uuid.uuid4(),
        series_id=series.id,
        artefact_id=artefact.id,
        date=as_of,
        value=stability_value,
    ).on_conflict_do_update(
        constraint="uq_series_point_date",
        set_={"value": stability_value, "artefact_id": artefact.id},
    )
    await db.execute(stmt)

    # Longer delay between countries to respect GDELT rate limits
    await asyncio.sleep(3)

    return [artefact.id]
