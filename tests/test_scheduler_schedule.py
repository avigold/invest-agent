"""Tests for scheduler cron job registration."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.daily import DailyScheduler


@pytest.mark.asyncio
async def test_scheduler_registers_all_jobs():
    """Scheduler should register 7 cron jobs when enabled."""
    mock_settings = MagicMock()
    mock_settings.scheduler_enabled = True
    mock_settings.scheduler_timezone = "UTC"

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=MagicMock())))
    mock_db.commit = AsyncMock()

    mock_sf = MagicMock()
    mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_scheduler_cls = MagicMock()
    mock_scheduler_instance = MagicMock()
    mock_scheduler_cls.return_value = mock_scheduler_instance

    scheduler = DailyScheduler(
        registry=MagicMock(),
        job_queue=MagicMock(),
        run_fn=MagicMock(),
        session_factory=mock_sf,
    )

    with (
        patch("app.scheduler.daily.get_settings", return_value=mock_settings),
        patch("app.scheduler.daily.AsyncIOScheduler", mock_scheduler_cls),
    ):
        await scheduler.start()

    # Should have registered 7 jobs
    assert mock_scheduler_instance.add_job.call_count == 7

    # Verify job IDs
    job_ids = {call.kwargs["id"] for call in mock_scheduler_instance.add_job.call_args_list}
    expected_ids = {
        "price_sync",
        "daily_macro_sync",
        "weekly_fmp_sync",
        "weekly_score_sync",
        "monthly_discover",
        "monthly_macro_sync",
        "monthly_rescore",
    }
    assert job_ids == expected_ids

    mock_scheduler_instance.start.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_disabled_when_not_enabled():
    """Scheduler should not start when SCHEDULER_ENABLED is false."""
    mock_settings = MagicMock()
    mock_settings.scheduler_enabled = False

    scheduler = DailyScheduler(
        registry=MagicMock(),
        job_queue=MagicMock(),
        run_fn=MagicMock(),
        session_factory=MagicMock(),
    )

    with patch("app.scheduler.daily.get_settings", return_value=mock_settings):
        await scheduler.start()

    # Scheduler should not have been created
    assert scheduler._scheduler is None
