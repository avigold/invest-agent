"""Echo handler: dummy job for testing the job system and SSE streaming."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.jobs.registry import LiveJob


async def echo_handler(
    job: LiveJob,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    message = job.params.get("message", "Hello from Invest Agent!")
    words = message.split()
    for i, word in enumerate(words, 1):
        line = f"[{i}] {word}"
        job.log_lines.append(line)
        job.queue.put(line)
        await asyncio.sleep(0.3)
    done_line = "Done."
    job.log_lines.append(done_line)
    job.queue.put(done_line)
