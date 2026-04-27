"""Tests for the causal-hop task family — the v2 headline novelty."""

from __future__ import annotations

import json
from pathlib import Path

from swegraph.cli import run_task
from swegraph.task_generators import generate_causal_hop_task
from swegraph.utils.import_graph import build_import_graph, hop_count


FIXTURES = Path(__file__).resolve().parents[1] / "swegraph" / "fixtures" / "repos"


def test_import_graph_distance_matches_chain():
    graph = build_import_graph(FIXTURES / "multi_pkg")
    # a -> b -> c (a should reach c through b)
    assert hop_count(graph, "multi_pkg.a", "multi_pkg.c") == 2
    assert hop_count(graph, "multi_pkg.b", "multi_pkg.c") == 1
    assert hop_count(graph, "multi_pkg.a", "multi_pkg.b") == 1
    # No backward edge
    assert hop_count(graph, "multi_pkg.c", "multi_pkg.a") is None


def test_causal_hop_task_records_hop_metadata():
    task = generate_causal_hop_task("task_test", seed=1, reward_config={})
    assert task.task_family == "causal_hop"
    assert "import_hops" in task.mutation_metadata
    assert task.mutation_metadata["import_hops"] in {1, 2}
    assert task.mutation_metadata.get("root_cause_file")


def test_oracle_passes_causal_hop(tmp_path: Path):
    task = generate_causal_hop_task("task_001", seed=2, reward_config={})
    p = tmp_path / "task.json"
    p.write_text(json.dumps(task.to_dict()))
    out = tmp_path / "run"
    run_task(p, "oracle", out)
    report = json.loads((out / "final_report.json").read_text())
    assert report["public_tests_pass"]
    assert report["hidden_tests_pass"]
    assert report["final_success"]
    assert report["causal_hop_metadata"]["import_hops"] in {1, 2}


def test_localization_milestone_fires_for_oracle(tmp_path: Path):
    task = generate_causal_hop_task("task_002", seed=3, reward_config={})
    p = tmp_path / "task.json"
    p.write_text(json.dumps(task.to_dict()))
    out = tmp_path / "run"
    run_task(p, "oracle", out)
    report = json.loads((out / "final_report.json").read_text())
    # Oracle reads the relevant_files (which includes root_cause_file) before
    # editing, so localization_correct must be True.
    assert report["milestone_completion"]["localization_correct"]
