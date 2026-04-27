"""Top-level entry point. Depends on b (which depends on c)."""

from multi_pkg.b import average, normalise


def process_batch(values: list[float], lo: float, hi: float) -> list[float]:
    """Normalise each value into [0, 1] given bounds ``[lo, hi]``."""
    return [normalise(v, lo, hi) for v in values]


def summarise(values: list[float]) -> dict[str, float]:
    """Return the mean and the normalised range of ``values``."""
    if not values:
        return {"mean": 0.0, "spread": 0.0}
    return {
        "mean": average(values),
        "spread": float(max(values) - min(values)),
    }
