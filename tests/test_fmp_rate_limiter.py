"""Tests for FMP rate limiter and 429 retry logic."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.ingest.fmp import FMPRateLimiter, _fmp_get, _rate_limiter


class TestFMPRateLimiter:
    """Rate limiter enforces per-second request limits."""

    @pytest.mark.asyncio
    async def test_enforces_interval(self):
        limiter = FMPRateLimiter(max_per_second=10.0)  # 100ms interval
        t0 = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        elapsed = time.monotonic() - t0
        # 5 requests at 10/s should take at least 0.4s (4 waits)
        assert elapsed >= 0.35  # allow small timing tolerance

    @pytest.mark.asyncio
    async def test_single_request_no_wait(self):
        limiter = FMPRateLimiter(max_per_second=5.0)
        t0 = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - t0
        assert elapsed < 0.25  # first request should not wait


class TestFmpGetRetry:
    """_fmp_get retries on 429 with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_on_429(self):
        """Should retry on 429 and succeed on subsequent attempt."""
        import app.ingest.fmp as fmp_mod

        # Reset rate limiter for clean test
        fmp_mod._rate_limiter = FMPRateLimiter(max_per_second=100.0)

        call_count = 0

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return httpx.Response(429, text="Too Many Requests")
            return httpx.Response(200, json={"symbol": "AAPL"})

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _fmp_get(client, "/profile", {"symbol": "AAPL"})

        assert resp.status_code == 200
        assert call_count == 2  # 1 retry

        # Clean up
        fmp_mod._rate_limiter = None

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Should raise after exhausting all retries."""
        import app.ingest.fmp as fmp_mod
        fmp_mod._rate_limiter = FMPRateLimiter(max_per_second=100.0)

        async def always_429(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="Too Many Requests")

        transport = httpx.MockTransport(always_429)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await _fmp_get(client, "/profile", {"symbol": "AAPL"})
            assert exc_info.value.response.status_code == 429

        fmp_mod._rate_limiter = None

    @pytest.mark.asyncio
    async def test_non_429_error_raises_immediately(self):
        """Non-429 errors should not trigger retry."""
        import app.ingest.fmp as fmp_mod
        fmp_mod._rate_limiter = FMPRateLimiter(max_per_second=100.0)

        call_count = 0

        async def error_500(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(500, text="Server Error")

        transport = httpx.MockTransport(error_500)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await _fmp_get(client, "/profile", {"symbol": "AAPL"})

        assert call_count == 1  # no retry

        fmp_mod._rate_limiter = None
