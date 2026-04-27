from __future__ import annotations

import json
from pathlib import Path

from swegraph.reward import DEFAULT_REWARD, RewardTracker, load_reward_config
from swegraph.schema import MilestoneState


def test_load_reward_config_json(tmp_path: Path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"public_tests_pass": 5.0, "step_cost": -0.02}))
    cfg = load_reward_config(p)
    assert cfg["public_tests_pass"] == 5.0
    assert cfg["step_cost"] == -0.02


def test_load_reward_config_yaml(tmp_path: Path):
    yaml = __import__("importlib").util.find_spec("yaml")
    if yaml is None:
        return  # PyYAML is optional
    p = tmp_path / "r.yaml"
    p.write_text("public_tests_pass: 7.0\nstep_cost: -0.03\n")
    cfg = load_reward_config(p)
    assert cfg["public_tests_pass"] == 7.0


def test_reward_tracker_awards_each_milestone_once():
    tracker = RewardTracker(DEFAULT_REWARD)
    m = MilestoneState(task_started=True, public_failure_reproduced=True)
    c1 = tracker.step(m)
    assert c1.get("public_failure_reproduced") == DEFAULT_REWARD["public_failure_reproduced"]
    c2 = tracker.step(m)
    # second step should NOT re-award the milestone
    assert "public_failure_reproduced" not in {k for k in c2 if not k.startswith("_")}


def test_reward_tracker_charges_negative_milestones_once():
    tracker = RewardTracker(DEFAULT_REWARD)
    m = MilestoneState(protected_files_unchanged=False)
    c = tracker.step(m)
    assert c["unrelated_files_changed"] == DEFAULT_REWARD["unrelated_files_changed"]
    c2 = tracker.step(m)
    assert "unrelated_files_changed" not in {k for k in c2 if not k.startswith("_")}
