"""Tests for the v2 hidden-validator abstraction."""

from __future__ import annotations

from pathlib import Path

from swegraph.validators import (
    coerce_legacy_hidden_tests,
    run_validators,
)


FIXTURES = Path(__file__).resolve().parents[1] / "swegraph" / "fixtures" / "repos"


def test_unit_tests_validator_passes_on_clean_repo(tmp_path: Path):
    import shutil

    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURES / "stats_utils", workspace)
    spec = {
        "kind": "unit_tests",
        "files": {
            "tests/test_smoke.py": (
                "from stats_utils.core import percentile\n\n"
                "def test_smoke():\n"
                "    assert percentile([1, 2, 3, 4], 75) == 3\n"
            )
        },
    }
    [r] = run_validators(workspace, [spec])
    assert r.passed, r.detail


def test_property_validator_catches_off_by_one(tmp_path: Path):
    import shutil

    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURES / "stats_utils", workspace)
    # Plant the v1 off-by-one mutation directly.
    src = workspace / "stats_utils" / "core.py"
    src.write_text(
        src.read_text().replace(
            "idx = int(round((len(sorted_vals) - 1) * (p / 100)))",
            "idx = int(round(len(sorted_vals) * (p / 100)))",
        )
    )
    spec = {
        "kind": "property",
        "module": "stats_utils.core",
        "function": "percentile",
        "strategy": [
            {"kind": "lists", "of": "integers", "min_value": -100, "max_value": 100, "min_size": 2, "max_size": 30},
            {"kind": "integers", "min_value": 0, "max_value": 100},
        ],
        "assertion": "result is None or (min(args[0]) <= result <= max(args[0]))",
        "max_examples": 80,
    }
    [r] = run_validators(workspace, [spec])
    # The buggy variant exceeds max(values) for some inputs; property must fail.
    assert not r.passed
    assert r.counterexample is not None


def test_metamorphic_extractor_finds_relations():
    from swegraph.utils.metamorphic_extract import extract_relations

    src = (
        "def test_x():\n"
        "    assert percentile(values, 0) == min(values)\n"
        "    assert percentile(values, 100) == max(values)\n"
        "    assert percentile(values, 50) == percentile(values, 50)\n"
    )
    rels = extract_relations(src, "percentile")
    assert "boundary_extrema" in rels
    assert "idempotent_under_call" in rels


def test_legacy_hidden_tests_back_compat():
    spec = {"hidden_validators": [], "hidden_tests": {"tests/x.py": "def test():\n    assert True"}}
    out = coerce_legacy_hidden_tests(spec)
    assert out and out[0]["kind"] == "unit_tests"
