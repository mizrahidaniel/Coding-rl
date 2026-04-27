"""Tests for the AST mutation operators."""

from __future__ import annotations

from pathlib import Path

from swegraph.ingest.mutators import (
    MUTATION_OPERATORS,
    enumerate_mutations,
    replace_at_line_col,
)


def test_off_by_one_finds_int_constants(tmp_path: Path):
    src = tmp_path / "m.py"
    src.write_text("def f(xs):\n    return xs[0] + 1\n")
    muts = [m for m in enumerate_mutations(src) if m.operator == "off_by_one"]
    operators = {(m.before, m.after) for m in muts}
    # 0 -> -1, 0 -> 1, 1 -> 0, 1 -> 2 should all be present
    assert ("0", "-1") in operators
    assert ("0", "1") in operators
    assert ("1", "0") in operators
    assert ("1", "2") in operators


def test_compare_swap_emits_flips(tmp_path: Path):
    src = tmp_path / "m.py"
    src.write_text("def f(a, b):\n    return a < b\n")
    muts = [m for m in enumerate_mutations(src) if m.operator == "compare_swap"]
    assert any(m.before == "<" and m.after == "<=" for m in muts)


def test_boolean_flip_emits_for_constants_and_boolops(tmp_path: Path):
    src = tmp_path / "m.py"
    src.write_text("def f(x):\n    return True and x\n")
    muts = [m for m in enumerate_mutations(src) if m.operator == "boolean_flip"]
    assert any(m.before == "True" and m.after == "False" for m in muts)
    assert any(m.before == "and" and m.after == "or" for m in muts)


def test_return_value_handles_empty_collections(tmp_path: Path):
    src = tmp_path / "m.py"
    src.write_text("def f():\n    return []\n")
    muts = [m for m in enumerate_mutations(src) if m.operator == "return_value"]
    assert any(m.before == "[]" and m.after == "[None]" for m in muts)


def test_binary_op_swaps_arithmetic(tmp_path: Path):
    src = tmp_path / "m.py"
    src.write_text("def f(a, b):\n    return a + b\n")
    muts = [m for m in enumerate_mutations(src) if m.operator == "binary_op"]
    assert any(m.before == "+" and m.after == "-" for m in muts)


def test_replace_at_line_col_round_trip(tmp_path: Path):
    src = tmp_path / "m.py"
    src.write_text("a = 1\nb = 2\n")
    # Replace the literal "1" on line 1 col 4
    ok = replace_at_line_col(src, 1, 4, "1", "9")
    assert ok
    assert src.read_text() == "a = 9\nb = 2\n"
    # Replace "2" on line 2 col 4
    ok = replace_at_line_col(src, 2, 4, "2", "0")
    assert ok
    assert src.read_text() == "a = 9\nb = 0\n"


def test_enumerate_skips_non_python(tmp_path: Path):
    src = tmp_path / "m.txt"
    src.write_text("def f(): return 1\n")
    assert enumerate_mutations(src) == []


def test_all_operators_registered():
    assert set(MUTATION_OPERATORS.keys()) == {
        "off_by_one",
        "compare_swap",
        "boolean_flip",
        "return_value",
        "binary_op",
    }
