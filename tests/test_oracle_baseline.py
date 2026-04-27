from pathlib import Path

from swegraph.cli import run_task
from swegraph.task import generate_tasks


def test_oracle_baseline_high_success(tmp_path: Path):
    tasks_dir = tmp_path / "tasks"
    tasks = generate_tasks(12, tasks_dir, seed=4)
    successes = 0
    for t in tasks:
        out = tmp_path / "runs" / t.stem
        run_task(t, "oracle", out)
        report = __import__("json").loads((out / "final_report.json").read_text())
        successes += int(report["hidden_tests_pass"])
    assert successes / len(tasks) >= 0.95
