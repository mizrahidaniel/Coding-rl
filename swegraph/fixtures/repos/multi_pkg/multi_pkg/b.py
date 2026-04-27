"""Middle module. Depends on c."""

from multi_pkg.c import clamp, safe_divide


def normalise(value: float, lo: float, hi: float) -> float:
    """Map ``value`` into [0, 1] given inclusive bounds [lo, hi]."""
    clamped = clamp(value, lo, hi)
    return safe_divide(clamped - lo, hi - lo)


def average(values: list[float]) -> float:
    """Mean of ``values``; 0.0 for empty input."""
    return safe_divide(sum(values), len(values))
