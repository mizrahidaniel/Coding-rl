from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swegraph.schema import TrajectoryStep


class TrajectoryLogger:
    def __init__(self, out_file: Path):
        self.out_file = out_file
        self.steps: list[TrajectoryStep] = []

    def add(self, step: TrajectoryStep) -> None:
        self.steps.append(step)
        self.out_file.parent.mkdir(parents=True, exist_ok=True)
        with self.out_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(step.__dict__) + "\n")

    def summary(self) -> dict[str, Any]:
        return {"steps": len(self.steps)}
