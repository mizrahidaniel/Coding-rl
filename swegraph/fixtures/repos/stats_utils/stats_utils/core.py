def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def percentile(values: list[float], p: int) -> float | None:
    if not values:
        return None
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    sorted_vals = sorted(values)
    idx = int(round((len(sorted_vals) - 1) * (p / 100)))
    return sorted_vals[idx]


def moving_average(values: list[float], window: int) -> list[float]:
    if window <= 0:
        raise ValueError("window must be > 0")
    return [sum(values[i : i + window]) / window for i in range(0, len(values) - window + 1)]


def normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if lo == hi:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]
