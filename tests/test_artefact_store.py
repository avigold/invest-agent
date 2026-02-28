"""Tests for ArtefactStore — uses a temp directory, mocks the DB session."""
from __future__ import annotations

import hashlib
import tempfile
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ingest.artefact_store import ArtefactStore


def _mock_session(existing_artefact=None):
    """Return an AsyncSession mock.  execute() returns a result whose
    scalar_one_or_none() yields *existing_artefact*."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_artefact
    session.execute.return_value = result
    return session


@pytest.fixture
def store(tmp_path):
    return ArtefactStore(str(tmp_path))


@pytest.mark.asyncio
async def test_store_writes_file_and_returns_artefact(store, tmp_path):
    db = _mock_session()
    ds_id = uuid.uuid4()
    content = '{"hello": "world"}'

    art = await store.store(
        db=db,
        data_source_id=ds_id,
        source_url="https://example.com",
        fetch_params={"key": "val"},
        content=content,
        time_window_start=date(2024, 1, 1),
        time_window_end=date(2024, 12, 31),
    )

    # Artefact was created
    assert art.content_hash == hashlib.sha256(content.encode()).hexdigest()
    assert art.size_bytes == len(content.encode())
    assert art.data_source_id == ds_id

    # File was written
    file_path = Path(art.storage_uri)
    assert file_path.exists()
    assert file_path.read_text() == content

    # db.add and db.flush were called
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_deduplicates_on_same_hash(store):
    """If an artefact with the same source+hash exists, return it without writing."""
    existing = MagicMock()
    existing.id = uuid.uuid4()
    existing.content_hash = hashlib.sha256(b"same content").hexdigest()

    db = _mock_session(existing_artefact=existing)
    ds_id = uuid.uuid4()

    art = await store.store(
        db=db,
        data_source_id=ds_id,
        source_url="https://example.com",
        fetch_params={},
        content="same content",
    )

    assert art is existing
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_store_creates_directory(tmp_path):
    sub = tmp_path / "nested" / "dir"
    store = ArtefactStore(str(sub))
    assert sub.exists()


@pytest.mark.asyncio
async def test_store_handles_bytes(store):
    db = _mock_session()
    content = b'{"binary": true}'

    art = await store.store(
        db=db,
        data_source_id=uuid.uuid4(),
        source_url="https://example.com",
        fetch_params={},
        content=content,
    )

    assert art.content_hash == hashlib.sha256(content).hexdigest()
    assert art.size_bytes == len(content)
