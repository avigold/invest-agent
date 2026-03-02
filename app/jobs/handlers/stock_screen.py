"""Handler for stock_screen job command."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Company, ScreenResult
from app.screen.common_features import analyze_common_features
from app.screen.fundamentals_snapshot import fetch_fundamentals_for_matches
from app.screen.price_history import fetch_extended_prices
from app.screen.return_scanner import find_threshold_windows

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob

SCREEN_VERSION = "screen_v1"


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def stock_screen_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run a historical stock screen."""
    params = job.params
    return_threshold = float(params.get("return_threshold", 3.0))
    window_years = int(params.get("window_years", 5))
    lookback_years = int(params.get("lookback_years", 20))
    include_fundamentals = params.get("include_fundamentals", True)
    screen_name = params.get(
        "name", f"{return_threshold * 100:.0f}% in {window_years}yr"
    )

    today = datetime.now(tz=timezone.utc).date()
    start_date = f"{today.year - lookback_years}-01-01"
    end_date = str(today)

    _log(job, f"Historical Stock Screen: {screen_name}")
    _log(
        job,
        f"  Threshold: {return_threshold * 100:.0f}% gain in {window_years}-year windows",
    )
    _log(job, f"  Lookback: {lookback_years} years ({start_date} to {end_date})")

    async with session_factory() as db:
        # Phase 1: Load universe from DB
        result = await db.execute(select(Company))
        companies = list(result.scalars().all())
        tickers = [c.ticker for c in companies]
        ticker_metadata = {
            c.ticker: {
                "name": c.name,
                "country_iso2": c.country_iso2,
                "gics_code": c.gics_code or "",
            }
            for c in companies
        }
        _log(job, f"Universe: {len(tickers)} companies from database")

        # Phase 2: Fetch extended price histories
        _log(job, "\n--- Fetching price histories ---")
        prices = await fetch_extended_prices(
            tickers,
            start_date,
            end_date,
            log_fn=lambda msg: _log(job, msg),
        )
        _log(job, f"Got price data for {len(prices)}/{len(tickers)} tickers")

        # Phase 3: Find threshold matches
        _log(
            job,
            f"\n--- Scanning for {return_threshold * 100:.0f}%+ windows ---",
        )
        matches = find_threshold_windows(
            prices,
            ticker_metadata,
            window_years,
            return_threshold,
            log_fn=lambda msg: _log(job, msg),
        )
        _log(
            job,
            f"\nFound {len(matches)} stocks with {return_threshold * 100:.0f}%+ returns",
        )

        if not matches:
            _log(
                job,
                "No matches found. Try lowering the threshold or increasing the lookback.",
            )
            screen_result = ScreenResult(
                user_id=job.user_id,
                job_id=job.id,
                screen_name=screen_name,
                screen_version=SCREEN_VERSION,
                params=params,
                summary={"total_screened": len(prices), "matches_found": 0},
                matches=[],
                artefact_ids=[],
            )
            db.add(screen_result)
            await db.commit()
            return

        # Phase 4: Fetch fundamentals at window start
        fundamentals: dict[str, dict] = {}
        if include_fundamentals:
            _log(job, "\n--- Fetching fundamentals at window start ---")
            fundamentals = await fetch_fundamentals_for_matches(
                matches,
                log_fn=lambda msg: _log(job, msg),
            )

        # Phase 5: Analyze common features
        _log(job, "\n--- Analyzing common features ---")
        common_features = analyze_common_features(matches, fundamentals)

        # Phase 6: Store results
        matches_json = [
            {
                "ticker": m.ticker,
                "name": m.name,
                "country_iso2": m.country_iso2,
                "gics_code": m.gics_code,
                "window_start": str(m.window_start),
                "window_end": str(m.window_end),
                "start_price": m.start_price,
                "end_price": m.end_price,
                "return_pct": round(m.return_pct, 4),
                "fundamentals_at_start": fundamentals.get(m.ticker, {}),
            }
            for m in matches
        ]

        summary = {
            "total_screened": len(prices),
            "matches_found": len(matches),
            "common_features": common_features,
        }

        screen_result = ScreenResult(
            user_id=job.user_id,
            job_id=job.id,
            screen_name=screen_name,
            screen_version=SCREEN_VERSION,
            params={
                "return_threshold": return_threshold,
                "window_years": window_years,
                "lookback_years": lookback_years,
                "include_fundamentals": include_fundamentals,
            },
            summary=summary,
            matches=matches_json,
            artefact_ids=[],
        )
        db.add(screen_result)
        await db.commit()

        # Log summary
        _log(job, f"\n=== Screen Results ===")
        _log(job, f"Screened: {len(prices)} companies")
        _log(job, f"Matches: {len(matches)}")
        if common_features.get("sector_distribution"):
            _log(
                job,
                f"Top sectors: {json.dumps(common_features['sector_distribution'])}",
            )
        rs = common_features.get("return_stats", {})
        if rs:
            _log(
                job,
                f"Returns: median={rs['median'] * 100:.0f}%, max={rs['max'] * 100:.0f}%",
            )
        _log(job, "Done.")
