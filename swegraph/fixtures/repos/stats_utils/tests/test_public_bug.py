from stats_utils.core import percentile


def test_percentile_midpoint():
    assert percentile([1, 2, 3, 4], 75) == 3
