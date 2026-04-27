"""Behavioural tests for the three scripted baselines.

These ensure the wedge documented in the README actually holds:
- oracle is the upper bound,
- do_nothing is the lower bound,
- naive is a partial heuristic that solves easy bugs but not config / feature
  tasks.
"""

from __future__ import annotations

import json
from pathlib import Path

from swegraph.cli import run_task
from swegraph.task import generate_tasks


def _report(out_dir: Path) -> dict:
    return json.loads((out_dir / "final_report.json").read_text())


def test_do_nothing_fails_hidden(tmp_path: Path):
    tasks = generate_tasks(3, tmp_path / "tasks", seed=11)
    for t in tasks:
        out = tmp_path / "runs" / f"do_nothing_{t.stem}"
        run_task(t, "do_nothing", out)
        report = _report(out)
        assert not report["hidden_tests_pass"], f"do_nothing should fail hidden tests on {t.stem}"
        assert not report["final_success"], f"do_nothing should not be final_success on {t.stem}"
        # but it should always produce a well-formed trajectory
        traj_lines = (out / "trajectory.jsonl").read_text().strip().splitlines()
        assert len(traj_lines) >= 1


def test_naive_solves_bug_injection_only(tmp_path: Path):
    tasks = generate_tasks(3, tmp_path / "tasks", seed=11)
    by_family: dict[str, dict] = {}
    for t in tasks:
        out = tmp_path / "runs" / f"naive_{t.stem}"
        run_task(t, "naive", out)
        report = _report(out)
        task_data = json.loads(t.read_text())
        by_family[task_data["task_family"]] = report
    assert by_family["bug_injection"]["hidden_tests_pass"], "naive must solve simple boundary bug"
    assert not by_family["config_bug"]["hidden_tests_pass"], "naive must not solve config rename"
    assert not by_family["feature_addition"]["hidden_tests_pass"], "naive must not solve feature add"


def test_trajectory_is_multi_step_for_oracle(tmp_path: Path):
    task = generate_tasks(1, tmp_path / "tasks", seed=2)[0]
    out = tmp_path / "run"
    run_task(task, "oracle", out)
    lines = (out / "trajectory.jsonl").read_text().strip().splitlines()
    # oracle: reproduce, read(s), patch, verify, finish - should be > 3 steps
    assert len(lines) >= 4
    types = [json.loads(line)["action_type"] for line in lines]
    assert types[0] == "run_command"
    assert types[-1] == "finish"
    assert "read_file" in types
    # at least one mutating action
    assert any(t in types for t in ("replace_text", "write_file", "apply_patch"))
