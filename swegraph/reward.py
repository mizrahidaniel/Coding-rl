from __future__ import annotations

from dataclasses import asdict

from swegraph.schema import MilestoneState


DEFAULT_REWARD = {
    "public_failure_reproduced": 0.2,
    "relevant_file_read": 0.1,
    "implementation_edited": 0.2,
    "public_tests_improved": 0.5,
    "public_tests_pass": 1.0,
    "hidden_tests_pass": 2.0,
    "protected_files_unchanged": 0.3,
    "no_test_deletion": 0.3,
    "invalid_command": -0.1,
    "repeated_noop": -0.05,
    "unrelated_files_changed": -0.2,
    "tests_deleted": -0.5,
    "step_cost": -0.01,
}


class RewardTracker:
    def __init__(self, config: dict[str, float] | None = None):
        self.config = {**DEFAULT_REWARD, **(config or {})}
        self.total = 0.0
        self._awarded: set[str] = set()

    def step(self, milestones: MilestoneState, penalties: dict[str, float] | None = None) -> dict[str, float]:
        comp: dict[str, float] = {"step_cost": self.config["step_cost"]}
        for name, value in asdict(milestones).items():
            if value and name in self.config and name not in self._awarded:
                comp[name] = self.config[name]
                self._awarded.add(name)
        if penalties:
            comp.update(penalties)
        inc = sum(comp.values())
        self.total += inc
        comp["_step_total"] = inc
        comp["_cumulative"] = self.total
        return comp
