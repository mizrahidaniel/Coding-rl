from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RewardBreakdown:
    components: dict[str, float] = field(default_factory=dict)
    total: float = 0.0


@dataclass
class MilestoneState:
    task_started: bool = False
    public_failure_reproduced: bool = False
    relevant_file_read: bool = False
    implementation_edited: bool = False
    public_tests_improved: bool = False
    public_tests_pass: bool = False
    hidden_tests_pass: bool = False
    protected_files_unchanged: bool = True
    no_test_deletion: bool = True
    final_submitted: bool = False


@dataclass
class TrajectoryStep:
    timestamp: str
    step_index: int
    action_type: str
    command: str | None = None
    edit_metadata: dict[str, Any] | None = None
    stdout_summary: str | None = None
    stderr_summary: str | None = None
    exit_code: int | None = None
    changed_files: list[str] = field(default_factory=list)
    public_test_status: dict[str, Any] = field(default_factory=dict)
    milestone_state: dict[str, Any] = field(default_factory=dict)
    reward_components: dict[str, float] = field(default_factory=dict)
    cumulative_reward: float = 0.0


@dataclass
class TaskSpec:
    task_id: str
    repo_id: str
    task_family: str
    language: str = "python"
    framework: str = "pytest"
    seed: int = 0
    user_prompt: str = ""
    formal_prompt: str = ""
    hidden_formal_spec: str = ""
    public_tests: list[str] = field(default_factory=list)
    hidden_tests: dict[str, str] = field(default_factory=dict)
    mutation_metadata: dict[str, Any] = field(default_factory=dict)
    oracle_metadata: dict[str, Any] = field(default_factory=dict)
    allowed_files: list[str] = field(default_factory=list)
    protected_files: list[str] = field(default_factory=list)
    expected_behavior: str = ""
    difficulty: dict[str, Any] = field(default_factory=dict)
    reward_config: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FinalReport:
    task_id: str
    public_tests_pass: bool
    hidden_tests_pass: bool
    lint_pass: bool | None
    protected_files_changed: list[str]
    tests_deleted_or_disabled: bool
    patch_size: dict[str, int]
    unrelated_files_changed: list[str]
    relevant_files_inspected: bool
    bug_reproduced: bool
    final_success: bool
    reward_total: float
    milestone_completion: dict[str, Any]
    trajectory_length: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
