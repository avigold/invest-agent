from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # TODO: cancel stale running jobs, start worker pool (Step 5)
    yield
    # Shutdown
    from app.db.session import dispose_engine
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="Invest Agent", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.app_url, "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)

    return app


app = create_app()
