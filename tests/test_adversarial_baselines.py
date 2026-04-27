"""Tests proving that adversarial baselines actually trigger guards / fail
hidden validators. v2 ships these as labelled negatives for PRM/critic
training - they only have value if they reliably fail.
"""

from __future__ import annotations

import json
from pathlib import Path

from swegraph.cli import run_task
from swegraph.task import generate_tasks


def _report(out_dir: Path) -> dict:
    return json.loads((out_dir / "final_report.json").read_text())


def test_test_content_edit_attacker_is_caught_by_guards(tmp_path: Path):
    tasks = generate_tasks(3, tmp_path / "tasks", seed=21)
    for t in tasks:
        out = tmp_path / "run" / t.stem
        run_task(t, "attack_test_content_edit", out)
        report = _report(out)
        assert not report["final_success"], f"{t.stem}: guard should block"
        assert report["guard_report"], f"{t.stem}: must produce guard hits"
        rules = {h["rule"] for h in report["guard_report"]}
        assert any(r in rules for r in ("assert_literal_true", "assert_short_circuit_true"))


def test_conftest_shadow_attacker_is_caught_by_guards(tmp_path: Path):
    tasks = generate_tasks(2, tmp_path / "tasks", seed=22)
    for t in tasks:
        out = tmp_path / "run" / t.stem
        run_task(t, "attack_conftest_shadow", out)
        report = _report(out)
        assert not report["final_success"], f"{t.stem}: shadow conftest must be blocked"
        rules = {h["rule"] for h in report["guard_report"]}
        assert "new_conftest_added" in rules


def test_public_test_overfit_attacker_caught_by_hidden_validators(tmp_path: Path):
    # The overfit attacker doesn't trigger guards; the hidden validators must.
    tasks = generate_tasks(3, tmp_path / "tasks", seed=23)
    failures = 0
    for t in tasks:
        family = json.loads(t.read_text())["task_family"]
        if family == "feature_addition":
            # the overfit attacker happens to be a correct implementation here
            continue
        out = tmp_path / "run" / t.stem
        run_task(t, "attack_public_test_overfit", out)
        report = _report(out)
        if not report["hidden_tests_pass"]:
            failures += 1
    assert failures >= 1, "hidden validators must catch overfit on at least one non-feature task"
