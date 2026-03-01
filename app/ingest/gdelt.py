"""GDELT political stability ingest via DOC 2.0 API.

Fetches instability-themed article volume AND total article volume per country,
computes the instability *ratio* (instability / total), and inverts to a 0-1
stability value.  This corrects for English-language media volume bias — the US
generates far more English articles than Switzerland, but if the same fraction
of each country's coverage is about instability, they score the same.

Themes queried: PROTEST, ARMEDCONFLICT, TERROR, POLITICAL_TURMOIL.
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
from app.ingest.freshness import FRESHNESS_HOURS

logger = logging.getLogger(__name__)

_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

_INSTABILITY_QUERY = (
    "sourcecountry:{fips} "
    "(theme:PROTEST OR theme:ARMEDCONFLICT OR theme:TERROR OR theme:POLITICAL_TURMOIL)"
)

_TOTAL_QUERY = "sourcecountry:{fips}"

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


async def _fetch_gdelt_csv(
    client: httpx.AsyncClient,
    query: str,
) -> str:
    """Fetch a timeline volume CSV from GDELT DOC API."""
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


async def _fetch_with_retries(
    client: httpx.AsyncClient,
    query: str,
    label: str,
    log_fn: Callable[[str], None],
) -> str | None:
    """Fetch a GDELT CSV with up to 3 retries."""
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            return await _fetch_gdelt_csv(client, query)
        except Exception as e:
            last_err = e
            if attempt < 2:
                log_fn(f"  GDELT {label}: attempt {attempt + 1} failed ({e}), retrying...")
                await asyncio.sleep(5)
    log_fn(f"  GDELT {label}: all attempts failed ({last_err})")
    return None


def _is_valid_csv(text: str | None) -> bool:
    return bool(text and text.lstrip("\ufeff").startswith("Date"))


async def ingest_gdelt_stability(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    gdelt_source: DataSource,
    country: Country,
    as_of: date,
    log_fn: Callable[[str], None],
    force: bool = False,
) -> list[uuid.UUID]:
    """Fetch instability ratio from GDELT DOC API, compute stability score.

    Makes two queries per country:
    1. Instability-themed article volume
    2. Total article volume (all themes)

    stability_value = 1.0 - (instability_vol / total_vol), clamped to [0, 1].
    Falls back to 0.5 if the API is unreachable or returns no data.
    """
    fips = _ISO2_TO_FIPS.get(country.iso2, country.iso2)

    # Freshness check
    if not force:
        existing = await artefact_store.find_fresh(
            db, gdelt_source.id,
            {"iso2": country.iso2},
            FRESHNESS_HOURS["gdelt"],
        )
        if existing is not None:
            log_fn(f"  GDELT stability: {country.iso2} — skipped (fresh)")
            return [existing.id]

    instability_query = _INSTABILITY_QUERY.format(fips=fips)
    total_query = _TOTAL_QUERY.format(fips=fips)

    instability_csv: str | None = None
    total_csv: str | None = None

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            instability_csv = await _fetch_with_retries(
                client, instability_query, f"{country.iso2} instability", log_fn,
            )
            # Brief pause between the two queries
            await asyncio.sleep(2)
            total_csv = await _fetch_with_retries(
                client, total_query, f"{country.iso2} total", log_fn,
            )
    except Exception as e:
        log_fn(f"  GDELT: {country.iso2} — client error: {e}, using fallback")
        logger.warning("GDELT client error for %s: %s", country.iso2, e)

    # Parse both CSVs
    instability_vol = (
        _parse_csv_and_average(instability_csv, as_of)
        if _is_valid_csv(instability_csv)
        else None
    )
    total_vol = (
        _parse_csv_and_average(total_csv, as_of)
        if _is_valid_csv(total_csv)
        else None
    )

    if instability_vol is not None and total_vol is not None and total_vol > 0:
        # Ratio: what fraction of this country's coverage is instability-themed.
        # For developed nations this typically ranges from 0.08 (NL) to 0.29 (US).
        # Use absolute_score with floor=0.05, ceiling=0.40 (lower ratio = more stable).
        from app.score.absolute import absolute_score

        instability_ratio = instability_vol / total_vol
        stability_value = absolute_score(
            instability_ratio, floor=0.05, ceiling=0.40, higher_is_better=False,
        ) / 100.0  # Store as 0-1, converted to 0-100 in scoring
        log_fn(
            f"  GDELT stability: {country.iso2} = {stability_value:.3f}"
            f" (instability_vol={instability_vol:.3f},"
            f" total_vol={total_vol:.3f},"
            f" ratio={instability_ratio:.4f})"
        )
    else:
        stability_value = _FALLBACK_VALUE
        reason = "no data"
        if instability_csv and not _is_valid_csv(instability_csv):
            reason = "non-CSV instability response"
        elif total_csv and not _is_valid_csv(total_csv):
            reason = "non-CSV total response"
        log_fn(f"  GDELT stability: {country.iso2} = {stability_value} (fallback, {reason})")

    # Build source URL for evidence chain (human-readable)
    source_url = (
        f"{_DOC_API_URL}?query={instability_query}&mode=timelinevol&format=csv&TIMESPAN=3m"
    )

    # Store the raw responses as artefact
    artefact_content = json.dumps({
        "instability_csv": instability_csv,
        "total_csv": total_csv,
        "instability_vol": instability_vol,
        "total_vol": total_vol,
        "stability_value": stability_value,
        "iso2": country.iso2,
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
