from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.routes_countries import router as countries_router
from app.api.routes_jobs import init_job_globals, router as jobs_router
from app.api.stripe_routes import router as stripe_router
from app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialise job system
    settings = get_settings()

    from app.db.session import _get_session_factory
    from app.jobs.queue import JobQueue
    from app.jobs.registry import JobRegistry
    from app.jobs.runner import make_run_fn

    registry = JobRegistry()
    job_queue = JobQueue(max_concurrent=settings.max_concurrent_heavy_jobs)

    session_factory = _get_session_factory()
    run_fn = make_run_fn(registry)

    # Load existing jobs from DB for display
    try:
        async with session_factory() as db:
            await registry.load_existing(db)
        logger.info("Job registry loaded")
    except Exception:
        logger.warning("Could not load existing jobs (DB may not be ready)")

    init_job_globals(registry, job_queue, run_fn)

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
    app.include_router(jobs_router)
    app.include_router(stripe_router)
    app.include_router(countries_router)

    return app


app = create_app()
