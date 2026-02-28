"""Artefact storage with content hashing and deduplication."""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select
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
