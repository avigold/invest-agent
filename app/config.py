from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://investagent:investagent@localhost:5433/investagent"
    database_url_sync: str = "postgresql://investagent:investagent@localhost:5433/investagent"

    google_client_id: str = ""
    google_client_secret: str = ""

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24 * 7  # 1 week

    stripe_secret_key: str = ""
    stripe_price_id: str = ""
    stripe_webhook_secret: str = ""

    app_url: str = "http://localhost:3000"

    max_concurrent_heavy_jobs: int = 4
    max_user_concurrent_jobs: int = 1

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
