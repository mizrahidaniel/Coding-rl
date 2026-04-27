import json
from pathlib import Path

from swegraph.cli import run_task
from swegraph.task import generate_tasks


def test_final_report_contains_fields(tmp_path: Path):
    task = generate_tasks(1, tmp_path / "tasks")[0]
    out = tmp_path / "run"
    run_task(task, "do_nothing", out)
    report = json.loads((out / "final_report.json").read_text())
    for key in ["reward_total", "milestone_completion", "public_tests_pass", "hidden_tests_pass"]:
        assert key in report
