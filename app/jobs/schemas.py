from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class JobCommand(str, Enum):
    COUNTRY_REFRESH = "country_refresh"
    INDUSTRY_REFRESH = "industry_refresh"
    COMPANY_REFRESH = "company_refresh"
    UNIVERSE_REFRESH = "universe_refresh"
    PACKET_BUILD = "packet_build"
    BACKFILL = "backfill"
    ECHO = "echo"  # dummy job for testing


class JobCreate(BaseModel):
    command: JobCommand
    params: dict = {}


class JobResponse(BaseModel):
    id: uuid.UUID
    command: str
    params: dict
    status: str
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobDetail(JobResponse):
    log_text: str | None = None
    queue_position: int | None = None
