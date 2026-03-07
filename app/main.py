from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.routes_companies import router as companies_router
from app.api.routes_company_search import router as company_search_router
from app.api.routes_recommendations import router as recommendations_router
from app.api.routes_scoring_profiles import router as scoring_profiles_router
from app.api.routes_screener import router as screener_router
from app.api.routes_predictions import router as predictions_router
from app.api.routes_countries import router as countries_router
from app.api.routes_industries import router as industries_router
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

    # Start scheduler if enabled
    from app.scheduler.daily import DailyScheduler
    scheduler = DailyScheduler(registry, job_queue, run_fn, session_factory)
    try:
        await scheduler.start()
    except Exception:
        logger.warning("Scheduler failed to start", exc_info=True)

    yield

    # Shutdown
    await scheduler.stop()
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
    app.include_router(industries_router)
    app.include_router(companies_router)
    app.include_router(company_search_router)
    app.include_router(recommendations_router)
    app.include_router(scoring_profiles_router)
    app.include_router(screener_router)
    app.include_router(predictions_router)
    app.include_router(admin_router)

    # Serve built frontend in production (when web/dist/ exists)
    dist_dir = Path(__file__).resolve().parent.parent / "web" / "dist"
    if dist_dir.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=dist_dir / "assets"),
            name="spa-assets",
        )

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            return FileResponse(dist_dir / "index.html")

    return app


app = create_app()
