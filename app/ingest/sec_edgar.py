"""SEC EDGAR Company Facts API ingest (XBRL)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanySeries, CompanySeriesPoint, DataSource
from app.ingest.artefact_store import ArtefactStore
from app.ingest.freshness import FRESHNESS_HOURS

_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"
_USER_AGENT = "InvestAgent/1.0 (admin@investagent.app)"


async def fetch_company_facts(
    client: httpx.AsyncClient,
    cik: str,
) -> tuple[dict, str]:
    """Fetch all XBRL facts for a company from SEC EDGAR.

    Returns (parsed facts dict, raw response text).
    CIK must be zero-padded to 10 digits.
    """
    url = f"{_BASE_URL}/CIK{cik}.json"
    resp = await client.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.text
    data = resp.json()
    return data, raw


def extract_annual_facts(
    facts: dict,
    concept_names: list[str],
    unit_key: str = "USD",
    form_type: str = "10-K",
) -> list[dict]:
    """Extract annual values for a concept from the EDGAR facts response.

    Tries each concept name in order (fallback chain).
    Returns list of {fiscal_year, value, filed, form, accn} sorted by fiscal_year desc.
    """
    tax_data = facts.get("facts", {}).get("us-gaap", {})

    for concept in concept_names:
        concept_data = tax_data.get(concept)
        if concept_data is None:
            continue

        units = concept_data.get("units", {})
        values = units.get(unit_key, [])

        if not values:
            values = units.get("USD/shares", [])
        if not values:
            values = units.get("pure", [])
        if not values:
            values = units.get("shares", [])

        # Filter to 10-K forms only, deduplicate by fiscal year
        annual: dict[int, dict] = {}
        for item in values:
            if item.get("form") != form_type:
                continue
            fy = item.get("fy")
            if fy is None:
                continue
            # Keep the latest filing for each fiscal year
            if fy not in annual or item.get("filed", "") > annual[fy].get("filed", ""):
                annual[fy] = item

        if annual:
            result = []
            for fy, item in sorted(annual.items(), reverse=True):
                result.append({
                    "fiscal_year": fy,
                    "value": item["val"],
                    "filed": item.get("filed", ""),
                    "form": item.get("form", ""),
                    "accn": item.get("accn", ""),
                })
            return result

    return []


async def ingest_edgar_for_company(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    edgar_source: DataSource,
    company: Company,
    concept_map: dict[str, list[str]],
    log_fn: Callable[[str], None],
    force: bool = False,
) -> list[uuid.UUID]:
    """Fetch EDGAR XBRL facts for a company, store artefact + series points.

    Args:
        concept_map: mapping of series_name -> [concept_name_1, concept_name_2, ...]

    Returns list of artefact IDs created.
    """
    artefact_ids: list[uuid.UUID] = []

    async with httpx.AsyncClient() as client:
        log_fn(f"  SEC EDGAR: {company.ticker} (CIK {company.cik})")

        # Freshness check
        if not force:
            existing = await artefact_store.find_fresh(
                db, edgar_source.id,
                {"cik": company.cik},
                FRESHNESS_HOURS["sec_edgar"],
            )
            if existing is not None:
                log_fn(f"    Skipped (fresh)")
                return [existing.id]

        try:
            facts, raw_text = await fetch_company_facts(client, company.cik)
        except httpx.HTTPError as e:
            log_fn(f"    WARN: Failed to fetch EDGAR data for {company.ticker}: {e}")
            return []

        # Store the full EDGAR response as one artefact per company
        artefact = await artefact_store.store(
            db=db,
            data_source_id=edgar_source.id,
            source_url=f"{_BASE_URL}/CIK{company.cik}.json",
            fetch_params={"cik": company.cik, "ticker": company.ticker},
            content=raw_text,
        )
        artefact_ids.append(artefact.id)

        # Extract and store each concept as a series
        for series_name, concept_names in concept_map.items():
            unit_key = "USD"
            if series_name == "eps_diluted":
                unit_key = "USD/shares"

            points = extract_annual_facts(facts, concept_names, unit_key=unit_key)

            if not points:
                log_fn(f"    No data for {series_name}")
                continue

            # Upsert series
            result = await db.execute(
                select(CompanySeries).where(
                    CompanySeries.company_id == company.id,
                    CompanySeries.series_name == series_name,
                )
            )
            series = result.scalar_one_or_none()
            if series is None:
                series = CompanySeries(
                    company_id=company.id,
                    series_name=series_name,
                    source="sec_edgar",
                    indicator_code=concept_names[0],
                    unit=unit_key.lower(),
                    frequency="annual",
                )
                db.add(series)
                await db.flush()

            # Upsert points
            for pt in points:
                fy = int(pt["fiscal_year"])
                stmt = pg_insert(CompanySeriesPoint).values(
                    id=uuid.uuid4(),
                    series_id=series.id,
                    artefact_id=artefact.id,
                    date=date(fy, 12, 31),
                    value=pt["value"],
                ).on_conflict_do_update(
                    constraint="uq_company_series_point_date",
                    set_={"value": pt["value"], "artefact_id": artefact.id},
                )
                await db.execute(stmt)

            log_fn(f"    {series_name}: {len(points)} annual values")

    return artefact_ids
