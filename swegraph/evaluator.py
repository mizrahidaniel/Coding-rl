from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from swegraph.schema import FinalReport, MilestoneState
from swegraph.utils.diffing import changed_files_from_workspace, compute_patch_size
from swegraph.utils.file_guard import collect_guard_hits, suspicious_pytest_changes, tests_deleted
from swegraph.tests_runner import run_pytest
from swegraph.validators import (
    ValidationResult,
    all_passed,
    coerce_legacy_hidden_tests,
    run_validators,
)


def _is_unrelated(path: str, allowed_files: list[str]) -> bool:
    if not allowed_files:
        return False
    for allowed in allowed_files:
        norm = allowed.rstrip("/")
        if path == norm:
            return False
        if path.startswith(norm + "/"):
            return False
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
    validator_results: list[ValidationResult] | None = None,
) -> FinalReport:
    pub = run_pytest(workspace, task.public_tests)

    # v2: validators are a discriminated union of unit_tests / property /
    # metamorphic. Legacy ``hidden_tests`` dict is coerced to a single
    # unit_tests validator.
    if validator_results is None:
        validator_specs = coerce_legacy_hidden_tests({
            "hidden_validators": task.hidden_validators,
            "hidden_tests": task.hidden_tests,
        })
        validator_results = run_validators(workspace, validator_specs)
    hidden_pass = all_passed(validator_results)

    changed = changed_files_from_workspace(workspace, baseline_snapshot)
    protected = [f for f in changed if f in task.protected_files]
    deleted_tests = tests_deleted(workspace, task.public_tests)
    suspicious = suspicious_pytest_changes(changed)
    guard_hits = collect_guard_hits(
        workspace,
        public_tests=task.public_tests,
        changed_files=changed,
        baseline_snapshot=baseline_snapshot,
    )
    blocking_hit = any(h.severity == "block" for h in guard_hits)

    diff = subprocess.run(["git", "diff"], cwd=workspace, text=True, capture_output=True).stdout
    patch_size = compute_patch_size(diff)
    relevant_files = task.mutation_metadata.get("relevant_files", [])
    relevant_inspected = bool(read_files and any(rf in read_files for rf in relevant_files))

    final_success = (
        pub["all_passed"]
        and hidden_pass
        and not protected
        and not deleted_tests
        and not suspicious
        and not blocking_hit
    )

    causal_meta: dict[str, Any] = {}
    if "import_hops" in task.mutation_metadata:
        causal_meta = {
            "import_hops": task.mutation_metadata["import_hops"],
            "root_cause_file": task.mutation_metadata.get("root_cause_file"),
            "localization_correct": milestones.localization_correct,
        }

    return FinalReport(
        task_id=task.task_id,
        public_tests_pass=pub["all_passed"],
        hidden_tests_pass=hidden_pass,
        lint_pass=None,
        protected_files_changed=protected,
        tests_deleted_or_disabled=deleted_tests or suspicious or blocking_hit,
        patch_size=patch_size,
        unrelated_files_changed=[f for f in changed if _is_unrelated(f, task.allowed_files)],
        relevant_files_inspected=relevant_inspected,
        bug_reproduced=milestones.public_failure_reproduced,
        final_success=final_success,
        reward_total=reward_total,
        milestone_completion=milestones.__dict__,
        trajectory_length=trajectory_steps,
        validator_results=[r.__dict__ for r in validator_results],
        guard_report=[h.to_dict() for h in guard_hits],
        causal_hop_metadata=causal_meta,
    )


def save_report(report: FinalReport, out_path: Path) -> None:
    out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
