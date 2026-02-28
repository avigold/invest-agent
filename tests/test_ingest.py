"""Tests for ingest modules — uses mocked HTTP responses and DB sessions."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ingest.world_bank import fetch_world_bank_indicator
from app.ingest.fred import fetch_fred_series
from app.ingest.imf import fetch_imf_indicator
from app.ingest.gdelt import ingest_gdelt_stability, _parse_csv_and_average, _FALLBACK_VALUE


# ---------------------------------------------------------------------------
# World Bank
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_world_bank_indicator_parses_response():
    wb_response = [
        {"page": 1, "pages": 1, "total": 2},
        [
            {"date": "2024", "value": 2.5, "indicator": {"id": "NY.GDP.MKTP.KD.ZG"}},
            {"date": "2023", "value": 1.8, "indicator": {"id": "NY.GDP.MKTP.KD.ZG"}},
            {"date": "2022", "value": None, "indicator": {"id": "NY.GDP.MKTP.KD.ZG"}},
        ],
    ]

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(wb_response)
    mock_resp.json.return_value = wb_response
    mock_resp.is_success = True
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    points, raw = await fetch_world_bank_indicator(mock_client, "US", "NY.GDP.MKTP.KD.ZG", 2020, 2024)

    assert len(points) == 2  # None values filtered out
    assert points[0] == {"date": "2024", "value": 2.5}
    assert points[1] == {"date": "2023", "value": 1.8}
    assert raw == json.dumps(wb_response)


@pytest.mark.asyncio
async def test_fetch_world_bank_empty_response():
    wb_response = [{"page": 1, "pages": 0, "total": 0}, None]

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(wb_response)
    mock_resp.json.return_value = wb_response
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    points, raw = await fetch_world_bank_indicator(mock_client, "XX", "NY.GDP.MKTP.KD.ZG", 2020, 2024)
    assert points == []


# ---------------------------------------------------------------------------
# FRED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_fred_series_parses_response():
    fred_response = {
        "observations": [
            {"date": "2024-01-01", "value": "5.33"},
            {"date": "2024-02-01", "value": "5.33"},
            {"date": "2024-03-01", "value": "."},  # missing
        ]
    }

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(fred_response)
    mock_resp.json.return_value = fred_response
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    observations, raw = await fetch_fred_series(mock_client, "FEDFUNDS", "testkey", "2024-01-01", "2024-12-31")

    assert len(observations) == 2  # "." filtered out
    assert observations[0] == {"date": "2024-01-01", "value": 5.33}


@pytest.mark.asyncio
async def test_fetch_fred_skips_empty_api_key():
    """ingest_fred_for_country should skip when api_key is empty."""
    from app.ingest.fred import ingest_fred_for_country

    db = AsyncMock()
    store = MagicMock()
    source = MagicMock()
    country = MagicMock()
    logs: list[str] = []

    result = await ingest_fred_for_country(
        db=db,
        artefact_store=store,
        fred_source=source,
        country=country,
        fred_series={"fedfunds": {"series_id": "FEDFUNDS", "name": "Fed Funds", "unit": "percent", "frequency": "monthly"}},
        api_key="",
        start_date="2024-01-01",
        end_date="2024-12-31",
        log_fn=logs.append,
    )

    assert result == []
    assert any("Skipping" in l for l in logs)


# ---------------------------------------------------------------------------
# IMF WEO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_imf_indicator_parses_response():
    imf_response = {
        "values": {
            "GGXWDG_NGDP": {
                "JPN": {
                    "2022": 248.200000000000005684,
                    "2023": 240.500000000000003421,
                    "2024": 236.100000000000001234,
                }
            }
        }
    }

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(imf_response)
    mock_resp.json.return_value = imf_response
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    points, raw = await fetch_imf_indicator(mock_client, "JPN", "GGXWDG_NGDP", 2022, 2024)

    assert len(points) == 3
    assert points[0] == {"date": "2022", "value": 248.2}
    assert points[1] == {"date": "2023", "value": 240.5}
    assert points[2] == {"date": "2024", "value": 236.1}
    assert raw == json.dumps(imf_response)


@pytest.mark.asyncio
async def test_fetch_imf_indicator_handles_empty():
    imf_response = {"values": {"GGXWDG_NGDP": {}}}

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(imf_response)
    mock_resp.json.return_value = imf_response
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    points, raw = await fetch_imf_indicator(mock_client, "XYZ", "GGXWDG_NGDP", 2022, 2024)
    assert points == []


# ---------------------------------------------------------------------------
# GDELT
# ---------------------------------------------------------------------------

_SAMPLE_GDELT_CSV = """Date,Series,Value
2026-01-15,Volume Intensity,2.5
2026-01-16,Volume Intensity,3.0
2026-01-17,Volume Intensity,2.0
2026-02-01,Volume Intensity,1.5
2026-02-02,Volume Intensity,2.0
2026-02-03,Volume Intensity,1.0
"""


def test_parse_csv_and_average_filters_by_month():
    """Should average only values from the target month."""
    avg = _parse_csv_and_average(_SAMPLE_GDELT_CSV, date(2026, 2, 1))
    assert avg == pytest.approx(1.5)  # mean(1.5, 2.0, 1.0)

    avg_jan = _parse_csv_and_average(_SAMPLE_GDELT_CSV, date(2026, 1, 1))
    assert avg_jan == pytest.approx(2.5)  # mean(2.5, 3.0, 2.0)


def test_parse_csv_and_average_returns_none_for_missing_month():
    """Should return None if no data points match the target month."""
    avg = _parse_csv_and_average(_SAMPLE_GDELT_CSV, date(2025, 6, 1))
    assert avg is None


@pytest.mark.asyncio
async def test_gdelt_ingest_with_real_data():
    """GDELT ingest should fetch CSV, compute stability, and store artefact."""
    mock_artefact = MagicMock()
    mock_artefact.id = uuid.uuid4()

    mock_store = AsyncMock()
    mock_store.store.return_value = mock_artefact

    mock_series = MagicMock()
    mock_series.id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_series

    db = AsyncMock()
    db.execute.return_value = mock_result

    gdelt_source = MagicMock()
    gdelt_source.id = uuid.uuid4()

    country = MagicMock()
    country.iso2 = "US"
    country.id = uuid.uuid4()

    logs: list[str] = []

    # Mock _fetch_gdelt_csv to return sample CSV
    with patch("app.ingest.gdelt._fetch_gdelt_csv", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = _SAMPLE_GDELT_CSV

        ids = await ingest_gdelt_stability(
            db=db,
            artefact_store=mock_store,
            gdelt_source=gdelt_source,
            country=country,
            as_of=date(2026, 2, 1),
            log_fn=logs.append,
        )

    assert ids == [mock_artefact.id]
    mock_store.store.assert_awaited_once()

    # Verify artefact content is the raw CSV (not a stub JSON)
    call_kwargs = mock_store.store.call_args[1]
    assert call_kwargs["content"] == _SAMPLE_GDELT_CSV
    assert "api.gdeltproject.org" in call_kwargs["source_url"]

    # Verify stability was computed: mean instability for Feb = 1.5
    # stability = 1.0 - (1.5 / 10.0) = 0.85
    assert any("0.850" in log for log in logs)


@pytest.mark.asyncio
async def test_gdelt_ingest_falls_back_on_api_failure():
    """GDELT ingest should use fallback value when the API fails."""
    mock_artefact = MagicMock()
    mock_artefact.id = uuid.uuid4()

    mock_store = AsyncMock()
    mock_store.store.return_value = mock_artefact

    mock_series = MagicMock()
    mock_series.id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_series

    db = AsyncMock()
    db.execute.return_value = mock_result

    gdelt_source = MagicMock()
    gdelt_source.id = uuid.uuid4()

    country = MagicMock()
    country.iso2 = "CH"
    country.id = uuid.uuid4()

    logs: list[str] = []

    with patch("app.ingest.gdelt._fetch_gdelt_csv", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = httpx.ConnectTimeout("timeout")

        ids = await ingest_gdelt_stability(
            db=db,
            artefact_store=mock_store,
            gdelt_source=gdelt_source,
            country=country,
            as_of=date(2026, 2, 1),
            log_fn=logs.append,
        )

    assert ids == [mock_artefact.id]
    assert any("fallback" in log for log in logs)
