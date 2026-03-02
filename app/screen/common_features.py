"""Analyze common features across matched stocks."""
from __future__ import annotations

import statistics
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.screen.return_scanner import ReturnMatch

# GICS code to sector name mapping
GICS_SECTORS = {
    "10": "Energy",
    "15": "Materials",
    "20": "Industrials",
    "25": "Consumer Discretionary",
    "30": "Consumer Staples",
    "35": "Health Care",
    "40": "Financials",
    "45": "Information Technology",
    "50": "Communication Services",
    "55": "Utilities",
    "60": "Real Estate",
}


def analyze_common_features(
    matches: list[ReturnMatch],
    fundamentals: dict[str, dict[str, float | None]],
) -> dict[str, Any]:
    """Compute statistical summary of shared features among matched stocks.

    Returns a dict with sector_distribution, country_distribution,
    return_stats, window_start_distribution, and fundamental_stats.
    """
    if not matches:
        return {
            "sector_distribution": {},
            "country_distribution": {},
            "return_stats": {},
            "window_start_distribution": {},
            "fundamental_stats": {},
        }

    # Sector distribution
    sectors: dict[str, int] = {}
    for m in matches:
        label = GICS_SECTORS.get(m.gics_code, m.gics_code or "Unknown")
        sectors[label] = sectors.get(label, 0) + 1
    sector_dist = dict(sorted(sectors.items(), key=lambda x: -x[1]))

    # Country distribution
    countries: dict[str, int] = {}
    for m in matches:
        countries[m.country_iso2] = countries.get(m.country_iso2, 0) + 1
    country_dist = dict(sorted(countries.items(), key=lambda x: -x[1]))

    # Return statistics
    returns = [m.return_pct for m in matches]
    return_stats = {
        "count": len(returns),
        "median": round(statistics.median(returns), 4),
        "mean": round(statistics.mean(returns), 4),
        "min": round(min(returns), 4),
        "max": round(max(returns), 4),
    }

    # Window start year distribution
    start_years: dict[int, int] = {}
    for m in matches:
        yr = m.window_start.year
        start_years[yr] = start_years.get(yr, 0) + 1
    year_dist = dict(sorted(start_years.items()))

    # Fundamental statistics
    all_metrics: dict[str, list[float]] = {}
    for ticker, fdata in fundamentals.items():
        for metric, value in fdata.items():
            if value is not None:
                all_metrics.setdefault(metric, []).append(value)

    fundamental_stats: dict[str, dict] = {}
    for metric, values in sorted(all_metrics.items()):
        stats: dict[str, Any] = {
            "count": len(values),
            "median": round(statistics.median(values), 4),
            "mean": round(statistics.mean(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }
        if len(values) >= 2:
            stats["stdev"] = round(statistics.stdev(values), 4)
        fundamental_stats[metric] = stats

    return {
        "sector_distribution": sector_dist,
        "country_distribution": country_dist,
        "return_stats": return_stats,
        "window_start_distribution": year_dist,
        "fundamental_stats": fundamental_stats,
    }
