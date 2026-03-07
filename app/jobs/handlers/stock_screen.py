"""Handler for stock_screen job command."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Company, ScreenResult
from app.screen.common_features import GICS_SECTORS, analyze_common_features
from app.screen.fundamentals_snapshot import (
    fetch_fundamentals_for_matches,
    fetch_fundamentals_for_observations,
)
from app.screen.price_history import fetch_extended_prices
from app.screen.return_scanner import find_threshold_windows

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def stock_screen_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run a historical stock screen (v1 or v2)."""
    params = job.params
    version = params.get("screen_version", "v1")
    if version == "v2":
        await _stock_screen_v2(job, session_factory, params)
    else:
        await _stock_screen_v1(job, session_factory, params)


async def _stock_screen_v1(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
    params: dict,
) -> None:
    """Run a v1 historical stock screen (cherry-picked best windows)."""
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
                screen_version="screen_v1",
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
            screen_version="screen_v1",
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


async def _stock_screen_v2(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
    params: dict,
) -> None:
    """Run a v2 stock screen with fixed forward returns + contrast analysis."""
    from app.screen.contrast import compute_catastrophe_profile, compute_contrast
    from app.screen.forward_scanner import generate_observations

    return_threshold = float(params.get("return_threshold", 3.0))
    window_years = int(params.get("window_years", 5))
    lookback_years = int(params.get("lookback_years", 20))
    catastrophe_threshold = float(params.get("catastrophe_threshold", -0.80))
    include_fundamentals = params.get("include_fundamentals", True)
    screen_name = params.get(
        "name", f"v2: {return_threshold * 100:.0f}% in {window_years}yr"
    )

    today = datetime.now(tz=timezone.utc).date()
    start_date = f"{today.year - lookback_years}-01-01"
    end_date = str(today)

    _log(job, f"Stock Screen v2: {screen_name}")
    _log(job, f"  Winner threshold: {return_threshold * 100:.0f}% forward return")
    _log(job, f"  Catastrophe threshold: {catastrophe_threshold * 100:.0f}% max drawdown")
    _log(job, f"  Forward window: {window_years} years")
    _log(job, f"  Lookback: {lookback_years} years ({start_date} to {end_date})")

    async with session_factory() as db:
        # Phase 1: Load universe
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
        _log(job, f"Universe: {len(tickers)} companies")

        # Phase 2: Fetch price histories
        _log(job, "\n--- Fetching price histories ---")
        prices = await fetch_extended_prices(
            tickers,
            start_date,
            end_date,
            log_fn=lambda msg: _log(job, msg),
        )
        _log(job, f"Got price data for {len(prices)}/{len(tickers)} tickers")

        # Phase 3: Generate fixed forward observations
        _log(job, "\n--- Generating fixed forward observations ---")
        observations = generate_observations(
            prices,
            ticker_metadata,
            window_years=window_years,
            return_threshold=return_threshold,
            catastrophe_threshold=catastrophe_threshold,
            log_fn=lambda msg: _log(job, msg),
        )

        if not observations:
            _log(job, "No observations generated. Insufficient price data.")
            screen_result = ScreenResult(
                user_id=job.user_id,
                job_id=job.id,
                screen_name=screen_name,
                screen_version="screen_v2",
                params=params,
                summary={"total_screened": len(prices), "total_observations": 0},
                matches=[],
                artefact_ids=[],
            )
            db.add(screen_result)
            await db.commit()
            return

        # Phase 4: Attach fundamentals to recent observations
        if include_fundamentals:
            _log(job, "\n--- Fetching fundamentals for observations ---")
            await fetch_fundamentals_for_observations(
                observations,
                log_fn=lambda msg: _log(job, msg),
            )

        # Phase 5: Contrast analysis
        _log(job, "\n--- Computing winner vs non-winner contrast ---")
        contrast = compute_contrast(observations)
        _log(job, f"Contrast features with sufficient data: {len(contrast.features)}")
        for fc in contrast.features[:5]:
            _log(job, f"  {fc.feature}: separation={fc.separation:.3f}, "
                       f"lift={fc.lift:.2f}, direction={fc.direction}")

        _log(job, "\n--- Computing catastrophe profile ---")
        catastrophe_profile = compute_catastrophe_profile(observations)
        _log(job, f"Catastrophe features: {len(catastrophe_profile.features)}")

        # Phase 6: Common features (sector/country distributions for winners)
        winner_obs = [o for o in observations if o.label == "winner"]
        _log(job, "\n--- Analyzing winner distributions ---")

        # Build sector/country distributions
        sectors: dict[str, int] = {}
        countries: dict[str, int] = {}
        for o in winner_obs:
            label = GICS_SECTORS.get(o.gics_code, o.gics_code or "Unknown")
            sectors[label] = sectors.get(label, 0) + 1
            countries[o.country_iso2] = countries.get(o.country_iso2, 0) + 1

        winner_count = len(winner_obs)
        catastrophe_count = sum(1 for o in observations if o.label == "catastrophe")
        base_rate = winner_count / len(observations) if observations else 0

        # Phase 7: Store results
        matches_json = [o.to_dict() for o in observations]

        summary = {
            "total_screened": len(prices),
            "total_observations": len(observations),
            "winner_count": winner_count,
            "catastrophe_count": catastrophe_count,
            "base_rate": round(base_rate, 4),
            "catastrophe_rate": round(
                catastrophe_count / len(observations), 4
            ) if observations else 0,
            "contrast": contrast.to_dict(),
            "catastrophe_profile": catastrophe_profile.to_dict(),
            "common_features": {
                "sector_distribution": dict(sorted(sectors.items(), key=lambda x: -x[1])),
                "country_distribution": dict(sorted(countries.items(), key=lambda x: -x[1])),
            },
        }

        screen_result = ScreenResult(
            user_id=job.user_id,
            job_id=job.id,
            screen_name=screen_name,
            screen_version="screen_v2",
            params={
                "screen_version": "v2",
                "return_threshold": return_threshold,
                "window_years": window_years,
                "lookback_years": lookback_years,
                "catastrophe_threshold": catastrophe_threshold,
                "include_fundamentals": include_fundamentals,
            },
            summary=summary,
            matches=matches_json,
            artefact_ids=[],
        )
        db.add(screen_result)
        await db.commit()

        # Log summary
        _log(job, f"\n=== Screen v2 Results ===")
        _log(job, f"Screened: {len(prices)} companies")
        _log(job, f"Observations: {len(observations)}")
        _log(job, f"Winners: {winner_count} ({base_rate * 100:.1f}% base rate)")
        _log(job, f"Catastrophes: {catastrophe_count}")
        if contrast.features:
            top = contrast.features[0]
            _log(job, f"Most discriminating feature: {top.feature} "
                       f"(separation={top.separation:.3f})")
        _log(job, "Done.")
