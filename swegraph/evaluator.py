from __future__ import annotations

import json
from pathlib import Path

from swegraph.schema import FinalReport, MilestoneState
from swegraph.tests_runner import run_hidden_tests, run_pytest
from swegraph.utils.diffing import changed_files_from_workspace, compute_patch_size
from swegraph.utils.file_guard import suspicious_pytest_changes, tests_deleted


def evaluate_run(task, workspace: Path, baseline_snapshot: dict[str, str], trajectory_steps: int, reward_total: float, milestones: MilestoneState) -> FinalReport:
    pub = run_pytest(workspace, task.public_tests)
    hid = run_hidden_tests(workspace, task.hidden_tests)
    changed = changed_files_from_workspace(workspace, baseline_snapshot)
    protected = [f for f in changed if f in task.protected_files]
    deleted_tests = tests_deleted(workspace, task.public_tests)
    suspicious = suspicious_pytest_changes(changed)
    diff_proc = __import__("subprocess").run(["git", "diff"], cwd=workspace, text=True, capture_output=True)
    patch = diff_proc.stdout
    patch_size = compute_patch_size(patch)
    relevant = any(rf in changed for rf in task.mutation_metadata.get("relevant_files", []))
    final_success = pub["all_passed"] and hid["all_passed"] and not protected and not deleted_tests and not suspicious
    return FinalReport(
        task_id=task.task_id,
        public_tests_pass=pub["all_passed"],
        hidden_tests_pass=hid["all_passed"],
        lint_pass=None,
        protected_files_changed=protected,
        tests_deleted_or_disabled=deleted_tests or suspicious,
        patch_size=patch_size,
        unrelated_files_changed=[f for f in changed if not any(f.startswith(p.split('/')[0]) for p in task.allowed_files)],
        relevant_files_inspected=relevant,
        bug_reproduced=milestones.public_failure_reproduced,
        final_success=final_success,
        reward_total=reward_total,
        milestone_completion=milestones.__dict__,
        trajectory_length=trajectory_steps,
    )


def save_report(report: FinalReport, out_path: Path) -> None:
    out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
