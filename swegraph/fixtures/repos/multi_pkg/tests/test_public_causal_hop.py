from multi_pkg.a import process_batch


def test_process_batch_within_bounds():
    out = process_batch([0, 5, 10], 0, 10)
    assert out == [0.0, 0.5, 1.0]


def test_process_batch_clamps_out_of_range():
    out = process_batch([-5, 15], 0, 10)
    # Public test only checks that out-of-range inputs are mapped into [0, 1].
    assert all(0.0 <= v <= 1.0 for v in out)
