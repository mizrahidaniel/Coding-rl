from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from swegraph.schema import MilestoneState


DEFAULT_REWARD: dict[str, float] = {
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


def load_reward_config(path: Path) -> dict[str, float]:
    """Load reward weights from YAML or JSON.

    YAML support is optional (only required if PyYAML is installed); JSON files
    are always supported.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise RuntimeError("PyYAML is required to load YAML reward configs") from e
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    return {k: float(v) for k, v in data.items()}


class RewardTracker:
    """Tracks dense reward across a trajectory.

    Each milestone is awarded once (the first time it flips True). Penalties
    can be applied per step. Step cost is a fixed negative reward each call.
    """

    def __init__(self, config: dict[str, float] | None = None):
        self.config = {**DEFAULT_REWARD, **(config or {})}
        self.total = 0.0
        self._awarded: set[str] = set()

    def step(
        self,
        milestones: MilestoneState,
        penalties: dict[str, float] | None = None,
    ) -> dict[str, float]:
        comp: dict[str, float] = {"step_cost": self.config["step_cost"]}
        for name, value in asdict(milestones).items():
            if value and name in self.config and name not in self._awarded:
                comp[name] = self.config[name]
                self._awarded.add(name)
        # Negative milestones: charge once when they flip from True to False.
        for inverse, penalty_key in (
            ("protected_files_unchanged", "unrelated_files_changed"),
            ("no_test_deletion", "tests_deleted"),
        ):
            if not getattr(milestones, inverse) and penalty_key not in self._awarded:
                comp[penalty_key] = self.config[penalty_key]
                self._awarded.add(penalty_key)
        if penalties:
            for k, v in penalties.items():
                if k in self._awarded:
                    continue
                comp[k] = v
                self._awarded.add(k)
        inc = sum(v for k, v in comp.items() if not k.startswith("_"))
        self.total += inc
        comp["_step_total"] = inc
        comp["_cumulative"] = self.total
        return comp
