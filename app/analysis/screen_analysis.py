"""AI-powered screen result analysis — identifies patterns among matched stocks."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.screen.common_features import GICS_SECTORS

logger = logging.getLogger(__name__)

ANALYSIS_VERSION = "screen_analysis_v1"
ANALYSIS_VERSION_V2 = "screen_analysis_v2"
MODEL_ID = "claude-sonnet-4-6"

PROMPT_TEMPLATE = """\
You are a quantitative investment research analyst. You have been given the results of a historical stock screen that identified companies achieving {return_threshold_pct}%+ returns over {window_years}-year rolling windows, scanning {lookback_years} years of history.

Your task: analyze the match data below and identify what these winners had in common BEFORE their run. Look for patterns that could help identify the next generation of exceptional performers.

## Screen Parameters
- Return threshold: {return_threshold_pct}% in {window_years}-year windows
- Companies screened: {total_screened}
- Matches found: {matches_found}

## Sector Distribution
{sector_distribution}

## Country Distribution
{country_distribution}

## Window Start Year Distribution
{year_distribution}

## Return Statistics
- Median: {return_median}%
- Mean: {return_mean}%
- Range: {return_min}% to {return_max}%

## Fundamental Profile at Window Start (across all matches)
{fundamental_stats}

## Individual Matches
{matches_detail}

## Instructions

Analyze these results and provide your findings in exactly 5 sections. Use the headers exactly as shown. Be specific — cite actual numbers, ratios, and counts from the data. Do not invent data. Focus on actionable patterns.

### Pattern Summary
What did these {matches_found} winners have in common? Identify the 3-5 most significant shared characteristics. Be specific about how many of the {matches_found} companies share each trait.

### Fundamental Profile
What did the financials look like before the run? Which metrics were most distinctive? Were these companies profitable or pre-profit? Capital-light or capital-heavy? Growing fast or steady? Identify the fundamental archetype.

### Sector and Geography
Are winners concentrated in specific sectors or geographies? What does this concentration (or lack thereof) tell us? Is it a structural advantage or a cyclical artifact?

### Timing Patterns
When did these runs start? Is there a relationship between entry timing and market conditions? Did runs cluster in specific macro environments (post-crisis, bull markets, rate cycles)?

### Caveats
What are the limitations of this analysis? Address survivorship bias, sample size, the difference between correlation and causation, and any other factors that should temper conclusions.
"""


def _format_distribution(dist: dict[str, int]) -> str:
    """Format a distribution dict as readable text."""
    lines = []
    for key, count in dist.items():
        lines.append(f"- {key}: {count}")
    return "\n".join(lines) if lines else "- (none)"


def _format_fundamental_stats(stats: dict[str, dict]) -> str:
    """Format fundamental statistics as a table."""
    if not stats:
        return "(no fundamental data available)"

    lines = []
    for metric, s in stats.items():
        median = s.get("median", 0)
        mean = s.get("mean", 0)
        mn = s.get("min", 0)
        mx = s.get("max", 0)
        count = s.get("count", 0)

        # Format based on metric type
        if metric in ("revenue", "fcf"):
            fmt = lambda v: f"${v / 1e9:.1f}B" if abs(v) >= 1e9 else f"${v / 1e6:.0f}M"
            lines.append(
                f"- {metric}: median={fmt(median)}, mean={fmt(mean)}, "
                f"range=[{fmt(mn)} to {fmt(mx)}], n={count}"
            )
        elif metric in ("roe", "net_margin", "asset_turnover"):
            lines.append(
                f"- {metric}: median={median * 100:.1f}%, mean={mean * 100:.1f}%, "
                f"range=[{mn * 100:.1f}% to {mx * 100:.1f}%], n={count}"
            )
        elif metric == "debt_equity":
            lines.append(
                f"- {metric}: median={median:.2f}x, mean={mean:.2f}x, "
                f"range=[{mn:.2f}x to {mx:.2f}x], n={count}"
            )
        else:
            lines.append(
                f"- {metric}: median={median:.4f}, mean={mean:.4f}, "
                f"range=[{mn:.4f} to {mx:.4f}], n={count}"
            )

    return "\n".join(lines)


def _format_matches_detail(matches: list[dict]) -> str:
    """Format individual matches with their fundamentals."""
    lines = []
    for m in matches:
        sector = GICS_SECTORS.get(m.get("gics_code", ""), m.get("gics_code", ""))
        fundas = m.get("fundamentals_at_start", {})
        funda_parts = []
        for k, v in fundas.items():
            if v is None:
                continue
            if k in ("revenue", "fcf"):
                funda_parts.append(
                    f"{k}=${v / 1e9:.1f}B" if abs(v) >= 1e9 else f"{k}=${v / 1e6:.0f}M"
                )
            elif k in ("roe", "net_margin", "asset_turnover"):
                funda_parts.append(f"{k}={v * 100:.1f}%")
            elif k == "debt_equity":
                funda_parts.append(f"{k}={v:.2f}x")
            else:
                funda_parts.append(f"{k}={v:.4f}")

        lines.append(
            f"- {m['ticker']} ({m['name']}, {sector}, {m['country_iso2']}): "
            f"+{m['return_pct'] * 100:.0f}% from {m['window_start']} to {m['window_end']}, "
            f"start=${m['start_price']:.2f}. "
            f"Fundamentals: {', '.join(funda_parts) if funda_parts else 'N/A'}"
        )

    return "\n".join(lines)


V2_SECTIONS = {
    "base_rate_context": "",
    "distinctive_features": "",
    "risk_factors": "",
    "sector_and_geography": "",
    "fundamentals_vs_price": "",
    "caveats": "",
}

V2_SECTION_MAP = {
    "### base rate context": "base_rate_context",
    "### distinctive features": "distinctive_features",
    "### risk factors": "risk_factors",
    "### sector and geography": "sector_and_geography",
    "### fundamentals vs price signals": "fundamentals_vs_price",
    "### caveats": "caveats",
}

V1_SECTIONS = {
    "pattern_summary": "",
    "fundamental_profile": "",
    "sector_and_geography": "",
    "timing_patterns": "",
    "caveats": "",
}

V1_SECTION_MAP = {
    "### pattern summary": "pattern_summary",
    "### fundamental profile": "fundamental_profile",
    "### sector and geography": "sector_and_geography",
    "### timing patterns": "timing_patterns",
    "### caveats": "caveats",
}


def _parse_sections(text: str, version: str = "v1") -> dict[str, str]:
    """Parse Claude response into structured sections."""
    if version == "v2":
        sections = dict(V2_SECTIONS)
        section_map = V2_SECTION_MAP
    else:
        sections = dict(V1_SECTIONS)
        section_map = V1_SECTION_MAP

    current_section = None
    current_lines: list[str] = []

    for line in text.split("\n"):
        lower = line.strip().lower()
        if lower in section_map:
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = section_map[lower]
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


PROMPT_TEMPLATE_V2 = """\
You are a quantitative investment research analyst. You have been given the results of a systematic stock screening study using fixed forward returns.

Instead of cherry-picking the best window per stock, this study evaluated every company at every annual observation point and measured what happened over the next {window_years} years. The study then contrasted companies that achieved {return_threshold_pct}%+ returns ("winners") against all other observations to identify what was actually distinctive.

## Study Parameters
- Forward window: {window_years} years
- Winner threshold: {return_threshold_pct}%+ total return
- Catastrophe threshold: {catastrophe_threshold_pct}% max drawdown
- Companies screened: {total_screened}
- Total observations: {total_observations}

## Base Rates
- Winner observations: {winner_count} ({base_rate_pct}% of all observations)
- Catastrophe observations: {catastrophe_count} ({catastrophe_rate_pct}%)
- Normal observations: {normal_count}

## Winner vs Non-Winner Contrast
(Features sorted by separation — how well they divide winners from non-winners)
{contrast_table}

## Catastrophe Risk Factors
(Features that predict forward drawdowns exceeding {catastrophe_threshold_pct}%)
{catastrophe_table}

## Sector Distribution (Winners)
{sector_distribution}

## Country Distribution (Winners)
{country_distribution}

## Instructions

Analyze these contrast results and provide your findings in exactly 6 sections. Use the headers exactly as shown. Be specific — cite the actual separation scores, lift values, and base rates. Do not invent data.

### Base Rate Context
How rare are {return_threshold_pct}%+ returns over {window_years} years? What does the {base_rate_pct}% base rate tell us about the difficulty of achieving this threshold? How should this calibrate expectations?

### Distinctive Features
Which features actually separated winners from non-winners? Focus on high-separation features (separation > 0.3). What was the magnitude of difference (lift)? Are these price-momentum signals, fundamental quality signals, or both?

### Risk Factors
What predicts catastrophe? Which features had the highest separation for catastrophe events? How can these be used defensively? Is there overlap between winner and catastrophe predictors?

### Sector and Geography
Are winners concentrated in specific sectors or geographies relative to the base population? Is this a structural advantage or a cyclical artifact?

### Fundamentals vs Price Signals
Of the features with data, which type of signal (trailing price-derived vs fundamental) was more predictive? What does this tell us about the relative importance of momentum vs quality?

### Caveats
Address: sample size and statistical significance, look-ahead bias in fundamentals (yfinance provides ~4 years of annual data), the difference between correlation and causation, regime dependence, and any features with low coverage.
"""


def _format_contrast_table(features: list[dict]) -> str:
    """Format contrast features as a readable table."""
    if not features:
        return "(no features with sufficient data)"

    lines = []
    for f in features:
        direction = "↑" if f.get("direction") == "higher" else "↓"
        lines.append(
            f"- {f['feature']} {direction}: "
            f"Winners median={f['winner_median']:.4f} vs "
            f"Non-winners median={f['non_winner_median']:.4f} | "
            f"Lift={f['lift']:.2f}x | "
            f"Separation={f['separation']:.3f} | "
            f"(n={f['winner_count']}/{f['non_winner_count']})"
        )
    return "\n".join(lines)


async def generate_screen_analysis(
    db: AsyncSession,
    screen_result: Any,
    log: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Generate AI pattern analysis for a screen result.

    Returns dict of parsed sections.
    """
    log = log or (lambda _: None)
    settings = get_settings()

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    summary = screen_result.summary or {}
    common_features = summary.get("common_features", {})
    params = screen_result.params or {}
    matches = screen_result.matches or []

    return_stats = common_features.get("return_stats", {})

    prompt = PROMPT_TEMPLATE.format(
        return_threshold_pct=int(params.get("return_threshold", 3.0) * 100),
        window_years=params.get("window_years", 5),
        lookback_years=params.get("lookback_years", 20),
        total_screened=summary.get("total_screened", 0),
        matches_found=summary.get("matches_found", 0),
        sector_distribution=_format_distribution(
            common_features.get("sector_distribution", {})
        ),
        country_distribution=_format_distribution(
            common_features.get("country_distribution", {})
        ),
        year_distribution=_format_distribution(
            common_features.get("window_start_distribution", {})
        ),
        return_median=f"{return_stats.get('median', 0) * 100:.0f}",
        return_mean=f"{return_stats.get('mean', 0) * 100:.0f}",
        return_min=f"{return_stats.get('min', 0) * 100:.0f}",
        return_max=f"{return_stats.get('max', 0) * 100:.0f}",
        fundamental_stats=_format_fundamental_stats(
            common_features.get("fundamental_stats", {})
        ),
        matches_detail=_format_matches_detail(matches),
    )

    log(f"Calling Claude API ({MODEL_ID})...")

    import asyncio
    from functools import partial

    def _call_api() -> str:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=MODEL_ID,
            max_tokens=3000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    loop = asyncio.get_running_loop()
    response_text = await loop.run_in_executor(None, _call_api)

    log("Parsing response...")
    sections = _parse_sections(response_text)

    return sections


async def generate_screen_analysis_v2(
    db: AsyncSession,
    screen_result: Any,
    log: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Generate AI pattern analysis for a v2 screen result (contrast-based).

    Returns dict of parsed sections.
    """
    log = log or (lambda _: None)
    settings = get_settings()

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    summary = screen_result.summary or {}
    common_features = summary.get("common_features", {})
    params = screen_result.params or {}
    contrast = summary.get("contrast", {})
    catastrophe_profile = summary.get("catastrophe_profile", {})

    total_obs = summary.get("total_observations", 0)
    winner_count = summary.get("winner_count", 0)
    catastrophe_count = summary.get("catastrophe_count", 0)
    normal_count = total_obs - winner_count - catastrophe_count

    base_rate = summary.get("base_rate", 0)
    catastrophe_rate = summary.get("catastrophe_rate", 0)

    prompt = PROMPT_TEMPLATE_V2.format(
        return_threshold_pct=int(params.get("return_threshold", 3.0) * 100),
        window_years=params.get("window_years", 5),
        catastrophe_threshold_pct=int(params.get("catastrophe_threshold", -0.80) * 100),
        total_screened=summary.get("total_screened", 0),
        total_observations=total_obs,
        winner_count=winner_count,
        base_rate_pct=f"{base_rate * 100:.1f}",
        catastrophe_count=catastrophe_count,
        catastrophe_rate_pct=f"{catastrophe_rate * 100:.1f}",
        normal_count=normal_count,
        contrast_table=_format_contrast_table(contrast.get("features", [])),
        catastrophe_table=_format_contrast_table(
            catastrophe_profile.get("features", [])
        ),
        sector_distribution=_format_distribution(
            common_features.get("sector_distribution", {})
        ),
        country_distribution=_format_distribution(
            common_features.get("country_distribution", {})
        ),
    )

    log(f"Calling Claude API ({MODEL_ID}) with v2 contrast prompt...")

    import asyncio

    def _call_api() -> str:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=MODEL_ID,
            max_tokens=4000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    loop = asyncio.get_running_loop()
    response_text = await loop.run_in_executor(None, _call_api)

    log("Parsing v2 response...")
    sections = _parse_sections(response_text, version="v2")

    return sections
