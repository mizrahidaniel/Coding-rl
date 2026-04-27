from __future__ import annotations

import json
import random
from pathlib import Path

from swegraph.reward import DEFAULT_REWARD
from swegraph.schema import TaskSpec
from swegraph.task_generators import (
    generate_bug_injection_task,
    generate_causal_hop_task,
    generate_config_bug_task,
    generate_feature_addition_task,
)


GENERATORS = [
    generate_bug_injection_task,
    generate_config_bug_task,
    generate_feature_addition_task,
    generate_causal_hop_task,
]


def save_task(task: TaskSpec, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(task.to_dict(), indent=2), encoding="utf-8")


def load_task(path: Path) -> TaskSpec:
    data = json.loads(path.read_text(encoding="utf-8"))
    # v1 -> v2 back-compat: drop fields the v2 dataclass does not know about
    # (rather than raise) and ensure required v2 fields default cleanly.
    allowed = TaskSpec.__dataclass_fields__.keys()
    filtered = {k: v for k, v in data.items() if k in allowed}
    return TaskSpec(**filtered)


def generate_tasks(
    num_tasks: int,
    out_dir: Path,
    seed: int = 7,
    reward_config: dict | None = None,
) -> list[Path]:
    rng = random.Random(seed)
    reward = {**DEFAULT_REWARD, **(reward_config or {})}
    out: list[Path] = []
    for i in range(num_tasks):
        family_idx = i % len(GENERATORS)
        task = GENERATORS[family_idx](f"task_{i+1:03d}", rng.randint(0, 10_000), reward)
        p = out_dir / f"{task.task_id}.json"
        save_task(task, p)
        out.append(p)
    return out
