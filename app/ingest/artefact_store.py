"""Artefact storage with content hashing and deduplication."""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, desc, cast, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artefact


class ArtefactStore:
    """Stores raw API responses as artefacts with SHA-256 content hashing."""

    def __init__(self, storage_dir: str) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def store(
        self,
        db: AsyncSession,
        data_source_id: uuid.UUID,
        source_url: str,
        fetch_params: dict,
        content: str | bytes,
        time_window_start: date | None = None,
        time_window_end: date | None = None,
    ) -> Artefact:
        """Store content, compute hash, deduplicate, return Artefact.

        If an artefact with the same (data_source_id, content_hash) already
        exists, returns the existing row without writing to disk again.
        """
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content

        content_hash = hashlib.sha256(content_bytes).hexdigest()

        # Check for existing artefact with same source + hash
        result = await db.execute(
            select(Artefact).where(
                Artefact.data_source_id == data_source_id,
                Artefact.content_hash == content_hash,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

        # Write to filesystem
        artefact_id = uuid.uuid4()
        file_path = self.storage_dir / f"{artefact_id}.json"
        file_path.write_bytes(content_bytes)

        # Insert DB row
        artefact = Artefact(
            id=artefact_id,
            data_source_id=data_source_id,
            source_url=source_url,
            fetch_params=fetch_params,
            fetched_at=datetime.now(tz=timezone.utc),
            time_window_start=time_window_start,
            time_window_end=time_window_end,
            content_hash=content_hash,
            storage_uri=str(file_path),
            size_bytes=len(content_bytes),
        )
        db.add(artefact)
        await db.flush()
        return artefact

    async def find_fresh(
        self,
        db: AsyncSession,
        data_source_id: uuid.UUID,
        fetch_params_filter: dict,
        max_age_hours: int,
    ) -> Artefact | None:
        """Find a recent artefact matching source and params filter.

        Uses JSONB containment (@>) to match fetch_params.
        Returns the most recent artefact if fetched within max_age_hours,
        otherwise None.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        query = (
            select(Artefact)
            .where(
                Artefact.data_source_id == data_source_id,
                Artefact.fetch_params.op("@>")(cast(fetch_params_filter, JSONB)),
                Artefact.fetched_at >= cutoff,
            )
            .order_by(desc(Artefact.fetched_at))
            .limit(1)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()
