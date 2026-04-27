"""End-to-end tests for the v3 real-repo ingestion pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from swegraph.cli import run_task
from swegraph.ingest import build_ingested_tasks, classify_mutation, split_tests
from swegraph.ingest.mutators import Mutation, enumerate_mutations


FIXTURE = Path(__file__).resolve().parents[1] / "swegraph" / "fixtures" / "repos" / "reqparse_lite"


def test_split_tests_produces_disjoint_function_sets(tmp_path: Path):
    test_paths = [
        str(p.relative_to(FIXTURE))
        for p in (FIXTURE / "tests").rglob("test_*.py")
    ]
    public, hidden = split_tests(FIXTURE, test_paths, seed=7, hidden_frac=0.3)
    assert public and hidden
    # Same fixture + same seed -> deterministic split
    pub2, hid2 = split_tests(FIXTURE, test_paths, seed=7, hidden_frac=0.3)
    assert pub2 == public
    assert hid2 == hidden


def test_classify_mutation_kills_a_known_bug(tmp_path: Path):
    # The v2 stats_utils off-by-one is a known catchable bug. Build the
    # mutation by hand and confirm the existing test suite kills it.
    fixture = Path(__file__).resolve().parents[1] / "swegraph" / "fixtures" / "repos" / "stats_utils"
    src_file = fixture / "stats_utils" / "core.py"
    src = src_file.read_text()
    target = "(len(sorted_vals) - 1) * (p / 100)"
    assert target in src
    line = next(i + 1 for i, ln in enumerate(src.splitlines()) if target in ln)
    col = src.splitlines()[line - 1].index(target)
    m = Mutation(
        operator="binary_op",
        path="stats_utils/core.py",
        line=line,
        col=col,
        before=target,
        after="len(sorted_vals) * (p / 100)",
    )
    res = classify_mutation(fixture, m, timeout=20)
    assert res.classification == "killed"


def test_ingest_pipeline_emits_decidable_tasks(tmp_path: Path):
    out_dir = tmp_path / "ingested"
    paths = build_ingested_tasks(
        fixture_dir=FIXTURE,
        out_dir=out_dir,
        seed=7,
        hidden_frac=0.3,
        max_tasks=4,
        timeout=20,
    )
    assert len(paths) >= 2, "expected at least 2 ingested tasks from reqparse_lite"
    for p in paths:
        spec = json.loads(p.read_text())
        assert spec["task_family"] == "real_repo_ingested"
        assert spec["public_test_overrides"]
        assert spec["mutation_metadata"].get("operator") in (
            "off_by_one", "compare_swap", "boolean_flip", "return_value", "binary_op"
        )


def test_oracle_solves_all_ingested_tasks(tmp_path: Path):
    out_dir = tmp_path / "ingested"
    paths = build_ingested_tasks(
        fixture_dir=FIXTURE,
        out_dir=out_dir,
        seed=7,
        hidden_frac=0.3,
        max_tasks=4,
        timeout=20,
    )
    assert paths
    for p in paths:
        run_dir = tmp_path / "runs" / p.stem
        run_task(p, "oracle", run_dir)
        report = json.loads((run_dir / "final_report.json").read_text())
        assert report["hidden_tests_pass"], f"{p.stem}: oracle must solve ingested task"


def test_do_nothing_fails_all_ingested_tasks(tmp_path: Path):
    out_dir = tmp_path / "ingested"
    paths = build_ingested_tasks(
        fixture_dir=FIXTURE,
        out_dir=out_dir,
        seed=7,
        hidden_frac=0.3,
        max_tasks=4,
        timeout=20,
    )
    assert paths
    for p in paths:
        run_dir = tmp_path / "runs" / p.stem
        run_task(p, "do_nothing", run_dir)
        report = json.loads((run_dir / "final_report.json").read_text())
        assert not report["hidden_tests_pass"], f"{p.stem}: do_nothing must NOT pass ingested task"
