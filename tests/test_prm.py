"""Tests for the PRM preference-pair emitter."""

from __future__ import annotations

import json
from pathlib import Path

from swegraph.prm import emit_prm_pairs
from swegraph.task import generate_tasks


def test_emit_prm_pairs_produces_useful_pairs(tmp_path: Path):
    tasks = generate_tasks(4, tmp_path / "tasks", seed=99)
    out_path = tmp_path / "pairs.jsonl"
    n = emit_prm_pairs(
        tasks=tasks,
        baselines=["oracle", "do_nothing", "attack_test_content_edit"],
        run_root=tmp_path / "runs",
        out_path=out_path,
    )
    assert n > 0
    pairs = [json.loads(line) for line in out_path.read_text().splitlines()]
    assert pairs, "must emit at least one preference pair"
    # Every pair has the required structure
    for p in pairs:
        assert p["preferred"]["baseline"] == "oracle"
        assert p["rejected"]["baseline"] != "oracle"
        assert "labels" in p
        assert "milestone_state" in p
    # At least one pair has preferred succeeding and rejected failing - the
    # high-signal preference shape.
    high_signal = [
        p for p in pairs
        if p["labels"]["preferred_final_success"]
        and not p["labels"]["rejected_final_success"]
    ]
    assert high_signal, "expected at least one (oracle_success, counterfactual_failure) pair"
