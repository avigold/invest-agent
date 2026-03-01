"""Universe-independent absolute scoring via clamped linear interpolation."""
from __future__ import annotations


def absolute_score(
    value: float | None,
    floor: float,
    ceiling: float,
    higher_is_better: bool = True,
) -> float:
    """Map a raw value to 0-100 using fixed thresholds.

    - ``floor`` maps to 0, ``ceiling`` maps to 100.
    - Values outside the range are clamped.
    - ``None`` returns 50.0 (neutral).
    - If ``floor == ceiling``, returns 50.0 (indeterminate).
    - When ``higher_is_better=False``, floor and ceiling are swapped
      internally so that a *lower* raw value produces a *higher* score.
    """
    if value is None:
        return 50.0

    if not higher_is_better:
        floor, ceiling = ceiling, floor

    if floor == ceiling:
        return 50.0

    # Linear interpolation then clamp to [0, 100]
    ratio = (value - floor) / (ceiling - floor)
    return max(0.0, min(100.0, ratio * 100.0))
