from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from swegraph.schema import FinalReport, MilestoneState
from swegraph.tests_runner import run_hidden_tests, run_pytest
from swegraph.utils.diffing import changed_files_from_workspace, compute_patch_size
from swegraph.utils.file_guard import suspicious_pytest_changes, tests_deleted


def _is_unrelated(path: str, allowed_files: list[str]) -> bool:
    if not allowed_files:
        return False
    for allowed in allowed_files:
        if path == allowed:
            return False
        if path.startswith(allowed.rstrip("/") + "/"):
            return False
    # Tolerate the ubiquitous package marker file by default.
    if path.endswith("__init__.py"):
        return False
    return True


def evaluate_run(
    task,
    workspace: Path,
    baseline_snapshot: dict[str, str],
    trajectory_steps: int,
    reward_total: float,
    milestones: MilestoneState,
    *,
    read_files: set[str] | None = None,
    hidden_status: dict[str, Any] | None = None,
) -> FinalReport:
    pub = run_pytest(workspace, task.public_tests)
    hid = hidden_status if hidden_status is not None else run_hidden_tests(workspace, task.hidden_tests)
    changed = changed_files_from_workspace(workspace, baseline_snapshot)
    protected = [f for f in changed if f in task.protected_files]
    deleted_tests = tests_deleted(workspace, task.public_tests)
    suspicious = suspicious_pytest_changes(changed)
    diff = subprocess.run(["git", "diff"], cwd=workspace, text=True, capture_output=True).stdout
    patch_size = compute_patch_size(diff)
    relevant_files = task.mutation_metadata.get("relevant_files", [])
    relevant_inspected = bool(read_files and any(rf in read_files for rf in relevant_files))
    final_success = (
        pub["all_passed"]
        and hid["all_passed"]
        and not protected
        and not deleted_tests
        and not suspicious
    )
    return FinalReport(
        task_id=task.task_id,
        public_tests_pass=pub["all_passed"],
        hidden_tests_pass=hid["all_passed"],
        lint_pass=None,
        protected_files_changed=protected,
        tests_deleted_or_disabled=deleted_tests or suspicious,
        patch_size=patch_size,
        unrelated_files_changed=[f for f in changed if _is_unrelated(f, task.allowed_files)],
        relevant_files_inspected=relevant_inspected,
        bug_reproduced=milestones.public_failure_reproduced,
        final_success=final_success,
        reward_total=reward_total,
        milestone_completion=milestones.__dict__,
        trajectory_length=trajectory_steps,
    )


def save_report(report: FinalReport, out_path: Path) -> None:
    out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
