"""Handler for screen_analysis job command.

Generates AI-powered pattern analysis + current candidate matches
for an existing screen result.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.screen_analysis import (
    ANALYSIS_VERSION,
    ANALYSIS_VERSION_V2,
    MODEL_ID,
    generate_screen_analysis,
    generate_screen_analysis_v2,
)
from app.db.models import ScreenResult
from app.screen.candidate_matcher import compute_winner_profile, score_candidates
from app.screen.common_features import GICS_SECTORS

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def screen_analysis_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Generate deep pattern analysis and current candidates for a screen result."""
    screen_result_id = job.params.get("screen_result_id", "")
    if not screen_result_id:
        _log(job, "ERROR: 'screen_result_id' param is required")
        job.status = "failed"
        return

    _log(job, f"Screen Analysis for result {screen_result_id}")

    async with session_factory() as db:
        # Load screen result
        result = await db.execute(
            select(ScreenResult).where(
                ScreenResult.id == uuid.UUID(screen_result_id),
                ScreenResult.user_id == job.user_id,
            )
        )
        screen = result.scalar_one_or_none()
        if screen is None:
            _log(job, "ERROR: Screen result not found or access denied")
            job.status = "failed"
            return

        matches = screen.matches or []
        if not matches:
            _log(job, "ERROR: No matches in this screen result — nothing to analyze")
            job.status = "failed"
            return

        # Route to v2 handler if screen_version is "screen_v2"
        if screen.screen_version == "screen_v2":
            await _screen_analysis_v2(job, db, screen)
            return

        _log(job, f"Screen: {screen.screen_name} — {len(matches)} matches (v1)")

        # Phase 1: Data quality assessment
        _log(job, "\n--- Data quality check ---")
        total_with_fundamentals = sum(
            1 for m in matches if m.get("fundamentals_at_start")
        )
        total_with_fiscal_date = sum(
            1 for m in matches
            if m.get("fundamentals_at_start", {}).get("_fiscal_date")
        )
        total_period_appropriate = sum(
            1 for m in matches
            if m.get("fundamentals_at_start", {}).get("_fiscal_gap_days") is not None
            and m["fundamentals_at_start"]["_fiscal_gap_days"] <= 365 * 3
        )
        _log(job, f"  {total_with_fundamentals}/{len(matches)} have fundamentals data")
        if total_with_fiscal_date > 0:
            _log(
                job,
                f"  {total_period_appropriate}/{total_with_fiscal_date} have "
                f"period-appropriate fundamentals (within 3yr of window start)",
            )
        else:
            _log(
                job,
                "  NOTE: No fiscal date metadata available — fundamentals may "
                "reflect current data rather than conditions at window start. "
                "Re-running the screen will capture date tracking.",
            )

        # Phase 2: Compute winner profile
        _log(job, "\n--- Computing winner profile ---")
        winner_profile = compute_winner_profile(matches)
        if not winner_profile:
            _log(
                job,
                "WARNING: Insufficient period-appropriate fundamental data for "
                "winner profile. Candidates will be scored on sector match only.",
            )
        else:
            _log(job, f"Winner profile: {len(winner_profile)} metrics with sufficient data")
        for metric, bounds in winner_profile.items():
            stale = bounds.get("stale_count", 0)
            stale_note = f", {stale} stale excluded" if stale else ""
            _log(
                job,
                f"  {metric}: P25={bounds['p25']:.4f} | median={bounds['median']:.4f} | "
                f"P75={bounds['p75']:.4f} (n={bounds['count']}{stale_note})",
            )

        # Phase 2: Score current candidates
        _log(job, "\n--- Scoring current candidates ---")
        # Build winner sectors set from match data
        winner_sectors: set[str] = set()
        for m in matches:
            sector = GICS_SECTORS.get(m.get("gics_code", ""), "")
            if sector:
                winner_sectors.add(sector)

        exclude_tickers = {m["ticker"] for m in matches}
        _log(job, f"Excluding {len(exclude_tickers)} tickers already in matches")
        _log(job, f"Winner sectors: {', '.join(sorted(winner_sectors)) or '(none)'}")

        candidates = await score_candidates(
            db, winner_profile, winner_sectors, exclude_tickers, top_n=20
        )
        _log(job, f"Found {len(candidates)} current candidates")
        for c in candidates[:5]:
            _log(
                job,
                f"  {c['ticker']} ({c['name']}): score={c['match_score']:.2f} — {', '.join(c['matching_factors'])}",
            )
        if len(candidates) > 5:
            _log(job, f"  ... and {len(candidates) - 5} more")

        # Phase 3: AI pattern analysis
        _log(job, "\n--- Generating AI pattern analysis ---")
        try:
            sections = await generate_screen_analysis(
                db, screen, log=lambda msg: _log(job, msg)
            )
        except Exception as e:
            _log(job, f"ERROR generating analysis: {e}")
            job.status = "failed"
            return

        _log(job, f"Analysis complete: {sum(len(v) for v in sections.values())} chars across {len(sections)} sections")

        # Phase 4: Store results
        _log(job, "\n--- Storing analysis ---")
        screen.analysis = {
            "model_id": MODEL_ID,
            "analysis_version": ANALYSIS_VERSION,
            "sections": sections,
            "current_candidates": candidates,
            "winner_profile": winner_profile,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        await db.commit()

        _log(job, f"\n=== Analysis Complete ===")
        _log(job, f"Sections: {', '.join(k for k, v in sections.items() if v)}")
        _log(job, f"Candidates: {len(candidates)}")
        _log(job, "Done.")


async def _screen_analysis_v2(
    job: "LiveJob",
    db: AsyncSession,
    screen: ScreenResult,
) -> None:
    """v2 analysis: contrast-based analysis + discrimination-weighted candidates."""
    from app.screen.candidate_scorer import score_candidates_v2
    from app.screen.contrast import ContrastProfile, FeatureContrast

    summary = screen.summary or {}
    _log(job, f"Screen: {screen.screen_name} (v2)")
    _log(job, f"  Observations: {summary.get('total_observations', 0)}")
    _log(job, f"  Winners: {summary.get('winner_count', 0)} "
              f"({summary.get('base_rate', 0) * 100:.1f}% base rate)")
    _log(job, f"  Catastrophes: {summary.get('catastrophe_count', 0)}")

    # Phase 1: Reconstruct ContrastProfile from stored summary
    _log(job, "\n--- Loading contrast data ---")
    contrast_data = summary.get("contrast", {})
    catastrophe_data = summary.get("catastrophe_profile", {})

    def _rebuild_profile(data: dict) -> ContrastProfile:
        features = []
        for fd in data.get("features", []):
            features.append(FeatureContrast(
                feature=fd["feature"],
                winner_median=fd["winner_median"],
                winner_p25=fd["winner_p25"],
                winner_p75=fd["winner_p75"],
                non_winner_median=fd["non_winner_median"],
                non_winner_p25=fd["non_winner_p25"],
                non_winner_p75=fd["non_winner_p75"],
                winner_count=fd["winner_count"],
                non_winner_count=fd["non_winner_count"],
                lift=fd["lift"],
                separation=fd["separation"],
                direction=fd["direction"],
            ))
        return ContrastProfile(
            features=features,
            winner_count=data.get("winner_count", 0),
            non_winner_count=data.get("non_winner_count", 0),
            total_observations=data.get("total_observations", 0),
        )

    contrast = _rebuild_profile(contrast_data)
    catastrophe_profile = _rebuild_profile(catastrophe_data)

    _log(job, f"Contrast features: {len(contrast.features)}")
    for fc in contrast.features[:5]:
        _log(job, f"  {fc.feature}: separation={fc.separation:.3f}, "
                   f"lift={fc.lift:.2f}, direction={fc.direction}")

    # Phase 2: Score candidates using discrimination-weighted features
    _log(job, "\n--- Scoring current candidates (v2) ---")
    common_features = summary.get("common_features", {})
    winner_sectors: set[str] = set(common_features.get("sector_distribution", {}).keys())

    # Build exclude set from observations that are winners
    observations = screen.matches or []
    exclude_tickers = {o["ticker"] for o in observations if o.get("label") == "winner"}
    _log(job, f"Excluding {len(exclude_tickers)} winner tickers from candidates")
    _log(job, f"Winner sectors: {', '.join(sorted(winner_sectors)) or '(none)'}")

    candidates = await score_candidates_v2(
        db, contrast, catastrophe_profile, winner_sectors,
        exclude_tickers, top_n=20
    )
    _log(job, f"Found {len(candidates)} current candidates")
    for c in candidates[:5]:
        factors = [f["feature"] for f in c["matching_factors"]]
        _log(job, f"  {c['ticker']} ({c['name']}): "
                   f"score={c['match_score']:.2f} — {', '.join(factors)}")
    if len(candidates) > 5:
        _log(job, f"  ... and {len(candidates) - 5} more")

    # Phase 3: AI analysis (v2 prompt with contrast data)
    _log(job, "\n--- Generating AI pattern analysis (v2) ---")
    try:
        sections = await generate_screen_analysis_v2(
            db, screen, log=lambda msg: _log(job, msg)
        )
    except Exception as e:
        _log(job, f"ERROR generating analysis: {e}")
        job.status = "failed"
        return

    _log(job, f"Analysis complete: {sum(len(v) for v in sections.values())} chars "
              f"across {len(sections)} sections")

    # Phase 4: Store results
    _log(job, "\n--- Storing analysis ---")
    screen.analysis = {
        "model_id": MODEL_ID,
        "analysis_version": ANALYSIS_VERSION_V2,
        "sections": sections,
        "current_candidates": candidates,
        "contrast_summary": {
            "top_features": [
                {"feature": fc.feature, "separation": fc.separation,
                 "lift": fc.lift, "direction": fc.direction}
                for fc in contrast.features[:5]
            ],
        },
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    await db.commit()

    _log(job, f"\n=== Analysis Complete (v2) ===")
    _log(job, f"Sections: {', '.join(k for k, v in sections.items() if v)}")
    _log(job, f"Candidates: {len(candidates)}")
    _log(job, "Done.")
