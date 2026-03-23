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
    DATA_SYNC = "data_sync"
    ADD_COMPANIES_BY_MARKET_CAP = "add_companies_by_market_cap"
    RECOMMENDATION_ANALYSIS = "recommendation_analysis"
    STOCK_SCREEN = "stock_screen"
    SCREEN_ANALYSIS = "screen_analysis"
    PREDICTION_TRAIN = "prediction_train"
    PREDICTION_SCORE = "prediction_score"
    FMP_SYNC = "fmp_sync"
    PRICE_SYNC = "price_sync"
    SCORE_SYNC = "score_sync"
    MACRO_SYNC = "macro_sync"
    DISCOVER_COMPANIES = "discover_companies"
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
