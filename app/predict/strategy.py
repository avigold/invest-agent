"""Portfolio construction strategy — Kelly sizing with constraints.

Converts model predictions into portfolio weights, applying position limits,
sector diversification caps, and minimum probability thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass


# Strategy constants
MAX_POSITION_WEIGHT = 0.10       # 10% max in any single stock
MAX_SECTOR_WEIGHT = 0.30         # 30% max in any sector
MIN_PROBABILITY = 0.05           # 5% minimum to enter a position
KELLY_FRACTION = 0.25            # Quarter-Kelly
DEFAULT_AVG_WIN = 3.0            # Average winner return (4x = 300%)
DEFAULT_AVG_LOSS = -0.50         # Average loser return (-50%)


@dataclass
class Position:
    """A single portfolio position."""

    ticker: str
    probability: float
    kelly_raw: float
    weight: float           # Final constrained weight
    sector: str
    expected_return: float  # probability * avg_win + (1-p) * avg_loss


def kelly_fraction(
    p_win: float,
    avg_win: float = DEFAULT_AVG_WIN,
    avg_loss: float = DEFAULT_AVG_LOSS,
    fraction: float = KELLY_FRACTION,
) -> float:
    """Compute Kelly criterion fraction (scaled down).

    Kelly formula: f = p/|a| - q/b
    where p=win probability, q=1-p, a=avg loss, b=avg win.

    Args:
        p_win: Predicted probability of winning.
        avg_win: Average return for winners (e.g. 3.0 for 300%).
        avg_loss: Average return for losers (e.g. -0.50 for -50%).
        fraction: Kelly scaling factor (0.25 = quarter-Kelly).

    Returns:
        Position size as fraction of portfolio (0 to 1).
    """
    if p_win <= 0 or avg_win <= 0:
        return 0.0
    q = 1 - p_win
    f = p_win / abs(avg_loss) - q / avg_win
    return max(0.0, f * fraction)


def build_portfolio(
    predictions: list[dict],
    max_position: float = MAX_POSITION_WEIGHT,
    max_sector: float = MAX_SECTOR_WEIGHT,
    min_probability: float = MIN_PROBABILITY,
) -> list[Position]:
    """Build a constrained portfolio from model predictions.

    Args:
        predictions: List of dicts with keys:
            - ticker: str
            - probability: float (calibrated probability)
            - sector: str (GICS sector name)
        max_position: Maximum weight for any single position.
        max_sector: Maximum aggregate weight for any sector.
        min_probability: Minimum probability threshold to enter.

    Returns:
        List of Position objects with constrained weights, sorted by weight desc.
    """
    # Filter by minimum probability
    eligible = [p for p in predictions if p["probability"] >= min_probability]

    # Compute Kelly fractions
    positions = []
    for p in eligible:
        k = kelly_fraction(p["probability"])
        if k <= 0:
            continue
        positions.append(Position(
            ticker=p["ticker"],
            probability=p["probability"],
            kelly_raw=k,
            weight=min(k, max_position),
            sector=p.get("sector", "Unknown"),
            expected_return=(
                p["probability"] * DEFAULT_AVG_WIN +
                (1 - p["probability"]) * DEFAULT_AVG_LOSS
            ),
        ))

    # Sort by Kelly fraction descending (strongest conviction first)
    positions.sort(key=lambda p: -p.kelly_raw)

    # Apply sector constraints
    sector_weights: dict[str, float] = {}
    for pos in positions:
        current = sector_weights.get(pos.sector, 0.0)
        remaining = max_sector - current
        if remaining <= 0:
            pos.weight = 0.0
        elif pos.weight > remaining:
            pos.weight = remaining
        sector_weights[pos.sector] = sector_weights.get(pos.sector, 0.0) + pos.weight

    # Remove zero-weight positions
    positions = [p for p in positions if p.weight > 0]

    # Normalize if total exceeds 1.0
    total = sum(p.weight for p in positions)
    if total > 1.0:
        for p in positions:
            p.weight /= total

    # Sort by weight descending for display
    positions.sort(key=lambda p: -p.weight)

    return positions
