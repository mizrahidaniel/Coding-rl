"""Leaf module. Pure arithmetic; no other workspace imports."""


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp ``value`` to ``[lo, hi]``."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def safe_divide(numerator: float, denominator: float) -> float:
    """Return numerator/denominator, or 0.0 when denominator is 0."""
    if denominator == 0:
        return 0.0
    return numerator / denominator
