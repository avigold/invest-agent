"""Industry refresh handler: load rubric → score all country×sector combos → build packets."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Country,
    Industry,
    IndustryRiskRegister,
    IndustryScore,
    DecisionPacket,
)
from app.score.industry import (
    compute_industry_scores,
    detect_industry_risks,
    load_rubric,
)
from app.score.versions import INDUSTRY_CALC_VERSION
from app.packets.industry_packets import build_industry_packet

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def industry_refresh_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Orchestrate: upsert industries → load macro → score → detect risks → build packets."""
    # Parse params
    iso2_filter = job.params.get("iso2")  # None = all countries
    as_of_str = job.params.get("as_of")

    if as_of_str:
        as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date()
    else:
        today = datetime.now(tz=timezone.utc).date()
        as_of = today.replace(day=1)

    _log(job, f"Industry refresh: as_of={as_of}")

    async with session_factory() as db:
        # 1. Load rubric and upsert Industry rows
        rubric = load_rubric()
        _log(job, f"Loaded rubric with {len(rubric['sectors'])} sectors")

        industries: list[Industry] = []
        for sector_key, sector_cfg in rubric["sectors"].items():
            gics_code = sector_cfg["gics_code"]
            name = sector_cfg["label"]

            result = await db.execute(
                select(Industry).where(Industry.gics_code == gics_code)
            )
            industry = result.scalar_one_or_none()
            if industry is None:
                industry = Industry(gics_code=gics_code, name=name)
                db.add(industry)
                await db.flush()
                _log(job, f"  Created industry: {name} ({gics_code})")
            else:
                industry.name = name
            industries.append(industry)

        await db.commit()

        # 2. Load countries
        query = select(Country)
        if iso2_filter:
            query = query.where(Country.iso2 == iso2_filter)
        result = await db.execute(query)
        countries = list(result.scalars().all())

        if not countries:
            _log(job, f"No countries found (filter: {iso2_filter})")
            return

        _log(job, f"Scoring {len(industries)} sectors × {len(countries)} countries = {len(industries) * len(countries)} combinations")

        # 3. Compute all scores (percentile-ranked together)
        scores = await compute_industry_scores(
            db=db,
            industries=industries,
            countries=countries,
            as_of=as_of,
            log_fn=lambda msg: _log(job, msg),
        )

        # 4. Delete old scores for this as_of before inserting new ones
        await db.execute(
            delete(IndustryScore).where(
                IndustryScore.as_of == as_of,
                IndustryScore.calc_version == INDUSTRY_CALC_VERSION,
            )
        )
        for score in scores:
            db.add(score)
        await db.flush()

        # 5. Detect risks
        _log(job, "\n--- Risk Detection ---")
        # Build lookups
        industry_by_id = {ind.id: ind for ind in industries}
        country_by_id = {c.id: c for c in countries}

        all_risks: dict[str, list[IndustryRiskRegister]] = {}  # keyed by "gics:iso2"
        for score in scores:
            industry = industry_by_id[score.industry_id]
            country = country_by_id[score.country_id]
            key = f"{industry.gics_code}:{country.iso2}"

            # Clear old risks
            await db.execute(
                delete(IndustryRiskRegister).where(
                    IndustryRiskRegister.industry_id == industry.id,
                    IndustryRiskRegister.country_id == country.id,
                    IndustryRiskRegister.detected_at == as_of,
                )
            )

            risks = detect_industry_risks(
                industry, country, score, as_of, lambda msg: _log(job, msg),
            )
            for r in risks:
                db.add(r)
            all_risks[key] = risks

        await db.flush()

        # 6. Build decision packets
        _log(job, "\n--- Building Decision Packets ---")
        packet_ids: list[str] = []
        for score in scores:
            industry = industry_by_id[score.industry_id]
            country = country_by_id[score.country_id]
            key = f"{industry.gics_code}:{country.iso2}"
            risks = all_risks.get(key, [])

            packet = await build_industry_packet(
                db=db,
                industry=industry,
                country=country,
                score=score,
                risks=risks,
                all_scores=scores,
            )
            packet_ids.append(str(packet.id))

        await db.commit()

        # Store references on job
        if packet_ids:
            job.packet_id = packet_ids[0]

        _log(job, f"\nIndustry refresh complete. {len(scores)} scores, {len(packet_ids)} packets built.")
