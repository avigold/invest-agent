"""AI-powered recommendation analysis with deterministic caching.

MCP-tool-like design: structured input dict -> structured output dict.
No side effects beyond DB caching of generated analyses.

Analysis is generated via a user-triggered job, not synchronously.
The API endpoint only returns cached results.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Callable

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import RecommendationAnalysis

logger = logging.getLogger(__name__)

ANALYSIS_VERSION = "analysis_v1"
MODEL_ID = "claude-sonnet-4-6"

PROMPT_TEMPLATE = """\
You are an investment research analyst. Analyze the following recommendation data and provide a structured assessment.

## Recommendation Data

Ticker: {ticker}
Company: {company_name}
Classification: {classification} (composite score: {composite_score})
Rank: {rank} of {rank_total}

## Score Breakdown

- Company Score: {company_score} (weight: 60%)
- Country Score: {country_score} (weight: 20%)
- Industry Score: {industry_score} (weight: 20%)

## Country Context ({country_name}, {country_iso2})

{country_packet_summary}

## Industry Context ({industry_name}, GICS {gics_code})

{industry_packet_summary}

## Company Context ({ticker})

{company_packet_summary}

## Instructions

Provide your analysis in exactly 5 sections. Use the section headers exactly as shown. Each section should be 2-4 sentences of clear, factual analysis based only on the data provided. Do not invent data points or metrics not present in the input.

### Summary
A brief overall assessment of the recommendation signal and what drives it.

### Country Assessment
How the country environment supports or detracts from this investment.

### Industry Assessment
How industry dynamics and macro sensitivity affect the outlook.

### Company Assessment
How company-specific fundamentals and market metrics drive the score.

### Risks and Catalysts
Key risk factors and potential catalysts to watch.
"""


def compute_score_hash(recommendation: dict, packets: dict) -> str:
    """SHA-256 of canonical score JSON for cache key."""
    canonical = {
        "ticker": recommendation["ticker"],
        "composite_score": recommendation["composite_score"],
        "company_score": recommendation["company_score"],
        "country_score": recommendation["country_score"],
        "industry_score": recommendation["industry_score"],
        "classification": recommendation["classification"],
        "as_of": recommendation["as_of"],
        "country_packet": packets.get("country"),
        "industry_packet": packets.get("industry"),
        "company_packet": packets.get("company"),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, default=str).encode()
    ).hexdigest()


def compute_prompt_hash() -> str:
    """SHA-256 of prompt template for cache invalidation on prompt changes."""
    return hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest()


def _format_packet_summary(packet_content: dict | None) -> str:
    """Format a decision packet's content into a readable summary for the prompt."""
    if not packet_content:
        return "No data available."

    lines = []

    scores = packet_content.get("scores", {})
    if scores:
        lines.append("Scores:")
        for key, val in scores.items():
            lines.append(f"  - {key}: {val}")

    component = packet_content.get("component_data", {})
    if component:
        lines.append("Component Data:")
        for key, val in component.items():
            if isinstance(val, dict):
                lines.append(f"  {key}:")
                for k2, v2 in val.items():
                    lines.append(f"    - {k2}: {v2}")
            else:
                lines.append(f"  - {key}: {val}")

    risks = packet_content.get("risks", [])
    if risks:
        lines.append("Risks:")
        for r in risks:
            lines.append(f"  - [{r.get('severity', '?')}] {r.get('type', '?')}: {r.get('description', '')}")

    return "\n".join(lines) if lines else "No detailed data available."


def _parse_analysis_sections(text: str) -> dict:
    """Parse the model response into structured sections."""
    sections = {
        "summary": "",
        "country_assessment": "",
        "industry_assessment": "",
        "company_assessment": "",
        "risks_and_catalysts": "",
    }

    section_map = {
        "### summary": "summary",
        "### country assessment": "country_assessment",
        "### industry assessment": "industry_assessment",
        "### company assessment": "company_assessment",
        "### risks and catalysts": "risks_and_catalysts",
    }

    current_section = None
    current_lines: list[str] = []

    for line in text.split("\n"):
        lower = line.strip().lower()
        if lower in section_map:
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = section_map[lower]
            current_lines = []
        elif current_section is not None:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


async def get_cached_analysis(
    db: AsyncSession,
    ticker: str,
    score_hash: str,
) -> dict | None:
    """Return cached analysis if one exists for this ticker + score state.

    Returns dict with analysis sections + metadata, or None.
    """
    prompt_hash = compute_prompt_hash()
    result = await db.execute(
        select(RecommendationAnalysis).where(
            RecommendationAnalysis.ticker == ticker,
            RecommendationAnalysis.score_hash == score_hash,
            RecommendationAnalysis.prompt_hash == prompt_hash,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        **row.content,
        "model_id": row.model_id,
        "analysis_version": row.analysis_version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def generate_analysis(
    db: AsyncSession,
    recommendation: dict,
    packets: dict[str, dict | None],
    log: Callable[[str], None] | None = None,
) -> dict:
    """Generate AI analysis for a recommendation. Called from job handler.

    Args:
        db: Database session.
        recommendation: Full recommendation dict from compute_recommendations().
        packets: Dict with keys 'country', 'industry', 'company' mapping to
                 decision packet content dicts (or None if unavailable).
        log: Optional log callback for job logging.

    Returns:
        Dict with analysis sections + metadata.

    Raises:
        ValueError: If ANTHROPIC_API_KEY is not set.
        Exception: If API call fails.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    score_hash = compute_score_hash(recommendation, packets)
    prompt_hash = compute_prompt_hash()

    # Check cache first
    cached = await db.execute(
        select(RecommendationAnalysis).where(
            RecommendationAnalysis.ticker == recommendation["ticker"],
            RecommendationAnalysis.score_hash == score_hash,
            RecommendationAnalysis.prompt_hash == prompt_hash,
        )
    )
    cached_row = cached.scalar_one_or_none()
    if cached_row:
        if log:
            log(f"Found cached analysis for {recommendation['ticker']}")
        return {
            **cached_row.content,
            "model_id": cached_row.model_id,
            "analysis_version": cached_row.analysis_version,
        }

    # Build prompt
    prompt = PROMPT_TEMPLATE.format(
        ticker=recommendation["ticker"],
        company_name=recommendation["name"],
        classification=recommendation["classification"],
        composite_score=recommendation["composite_score"],
        rank=recommendation["rank"],
        rank_total=recommendation["rank_total"],
        company_score=recommendation["company_score"],
        country_score=recommendation["country_score"],
        industry_score=recommendation["industry_score"],
        country_name=packets.get("country", {}).get("country_name", "Unknown") if packets.get("country") else "Unknown",
        country_iso2=recommendation["country_iso2"],
        industry_name=packets.get("industry", {}).get("industry_name", "Unknown") if packets.get("industry") else "Unknown",
        gics_code=recommendation["gics_code"],
        country_packet_summary=_format_packet_summary(packets.get("country")),
        industry_packet_summary=_format_packet_summary(packets.get("industry")),
        company_packet_summary=_format_packet_summary(packets.get("company")),
    )

    if log:
        log(f"Calling Claude API ({MODEL_ID})...")

    # Call Claude API (sync client — runs in job thread, not event loop)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=MODEL_ID,
        max_tokens=1500,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    response_text = message.content[0].text

    if log:
        log("Parsing response...")

    # Parse into sections
    sections = _parse_analysis_sections(response_text)

    # Cache in DB
    analysis = RecommendationAnalysis(
        ticker=recommendation["ticker"],
        score_hash=score_hash,
        prompt_hash=prompt_hash,
        analysis_version=ANALYSIS_VERSION,
        model_id=MODEL_ID,
        content=sections,
    )
    db.add(analysis)
    try:
        await db.commit()
        if log:
            log("Analysis cached successfully")
    except Exception:
        await db.rollback()
        logger.warning("Failed to cache analysis for %s (likely duplicate)", recommendation["ticker"])

    return {
        **sections,
        "model_id": MODEL_ID,
        "analysis_version": ANALYSIS_VERSION,
    }
