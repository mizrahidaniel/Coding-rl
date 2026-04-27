from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from swegraph.actions import ActionAPI
from swegraph.baselines import BASELINES, Action
from swegraph.evaluator import evaluate_run, save_report
from swegraph.reward import DEFAULT_REWARD, RewardTracker, load_reward_config
from swegraph.sandbox import LocalSandbox
from swegraph.schema import MilestoneState, TrajectoryStep, utc_now_iso
from swegraph.task import generate_tasks, load_task
from swegraph.tests_runner import run_hidden_tests, run_pytest
from swegraph.trajectory import TrajectoryLogger
from swegraph.utils.diffing import changed_files_from_workspace, compute_patch_size
from swegraph.utils.file_guard import suspicious_pytest_changes, tests_deleted


FIXTURES = Path(__file__).parent / "fixtures" / "repos"


def _snapshot(workspace: Path) -> dict[str, str]:
    snap: dict[str, str] = {}
    for p in workspace.rglob("*"):
        if not p.is_file():
            continue
        if ".git" in p.parts or "__pycache__" in p.parts or ".pytest_cache" in p.parts:
            continue
        snap[str(p.relative_to(workspace))] = p.read_text(encoding="utf-8", errors="ignore")
    return snap


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=workspace, capture_output=True, text=True)


def _apply_mutation(task, api: ActionAPI) -> None:
    mm = task.mutation_metadata
    if mm.get("type") == "replace_text":
        api.replace_text(mm["path"], mm["old"], mm["new"])


def _is_implementation_file(path: str) -> bool:
    return (
        path.endswith(".py")
        and not path.startswith("tests/")
        and "/tests/" not in path
        and not path.endswith("conftest.py")
    )


def _update_milestones(
    milestones: MilestoneState,
    *,
    action: Action,
    pre_failed: int,
    post: dict[str, Any] | None,
    changed_files: list[str],
    read_files: set[str],
    relevant_files: list[str],
    protected_files: list[str],
    public_tests: list[str],
    workspace: Path,
    finished: bool,
) -> dict[str, float]:
    """Update milestones in place; return per-step penalties dict."""
    penalties: dict[str, float] = {}

    if action.action_type == "read_file":
        path = action.args.get("path", "")
        if path in relevant_files:
            milestones.relevant_file_read = True

    if action.action_type in ("write_file", "replace_text", "apply_patch"):
        for f in changed_files:
            if _is_implementation_file(f):
                milestones.implementation_edited = True

    if post is not None:
        if not milestones.public_failure_reproduced and post["failed"] > 0:
            milestones.public_failure_reproduced = True
        if post["failed"] < pre_failed:
            milestones.public_tests_improved = True
        milestones.public_tests_pass = post["all_passed"]

    # Guards (recomputed every step so penalties trigger as soon as something
    # bad happens, not only at final eval).
    protected_changed = [f for f in changed_files if f in protected_files]
    if protected_changed:
        milestones.protected_files_unchanged = False
        penalties["unrelated_files_changed"] = -0.2
    if tests_deleted(workspace, public_tests) or suspicious_pytest_changes(changed_files):
        milestones.no_test_deletion = False
        penalties["tests_deleted"] = -0.5

    if finished:
        milestones.final_submitted = True
    return penalties


def _action_to_step(
    *,
    step_index: int,
    action: Action,
    pre_pub: dict[str, Any] | None,
    post_pub: dict[str, Any] | None,
    changed_files: list[str],
    milestones: MilestoneState,
    reward_components: dict[str, float],
    cumulative_reward: float,
) -> TrajectoryStep:
    cmd = action.args.get("command") if action.action_type == "run_command" else None
    edit_meta = None
    if action.action_type in ("write_file", "replace_text", "apply_patch", "read_file"):
        edit_meta = {k: v for k, v in action.args.items() if k != "content"}
        edit_meta["note"] = action.note
    stdout_summary = action.args.get("stdout_summary")
    stderr_summary = action.args.get("stderr_summary")
    exit_code = action.args.get("exit_code")
    return TrajectoryStep(
        timestamp=utc_now_iso(),
        step_index=step_index,
        action_type=action.action_type,
        command=cmd,
        edit_metadata=edit_meta,
        stdout_summary=stdout_summary,
        stderr_summary=stderr_summary,
        exit_code=exit_code,
        changed_files=changed_files,
        public_test_status=post_pub or {},
        milestone_state=milestones.__dict__.copy(),
        reward_components=reward_components,
        cumulative_reward=cumulative_reward,
    )


def _write_replay(
    out_dir: Path,
    task,
    steps: list[TrajectoryStep],
    final_report,
) -> None:
    lines = [
        f"# Replay: {task.task_id} ({task.task_family} on {task.repo_id})",
        "",
        f"**User prompt:** {task.user_prompt}",
        "",
        f"**Hidden spec:** {task.hidden_formal_spec}",
        "",
        "## Steps",
        "",
        "| # | action | summary | tests passed/failed | reward Δ | cum |",
        "| - | ------ | ------- | ------------------- | -------- | --- |",
    ]
    for s in steps:
        summary = s.command or ""
        if s.action_type in ("read_file", "write_file", "replace_text") and s.edit_metadata:
            summary = s.edit_metadata.get("path", "") + " " + s.edit_metadata.get("note", "")
        elif s.action_type == "finish":
            summary = "submit"
        tests = ""
        if s.public_test_status:
            tests = f"{s.public_test_status.get('passed', 0)}p/{s.public_test_status.get('failed', 0)}f"
        delta = s.reward_components.get("_step_total", 0.0) if s.reward_components else 0.0
        lines.append(
            f"| {s.step_index} | {s.action_type} | {summary[:60]} | {tests} | {delta:+.2f} | {s.cumulative_reward:+.2f} |"
        )
    lines += [
        "",
        "## Final report",
        "",
        f"- public tests pass: **{final_report.public_tests_pass}**",
        f"- hidden tests pass: **{final_report.hidden_tests_pass}**",
        f"- final success: **{final_report.final_success}**",
        f"- protected files changed: {final_report.protected_files_changed or 'none'}",
        f"- tests deleted/disabled: {final_report.tests_deleted_or_disabled}",
        f"- unrelated files changed: {final_report.unrelated_files_changed or 'none'}",
        f"- relevant files inspected: {final_report.relevant_files_inspected}",
        f"- bug reproduced: {final_report.bug_reproduced}",
        f"- patch size: {final_report.patch_size}",
        f"- reward total: {final_report.reward_total:+.2f}",
        f"- trajectory length: {final_report.trajectory_length}",
        "",
        "## Milestones",
        "",
    ]
    for k, v in final_report.milestone_completion.items():
        mark = "x" if v else " "
        lines.append(f"- [{mark}] {k}")
    (out_dir / "replay.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_task(
    task_path: Path,
    baseline: str,
    out_dir: Path,
    mode: str = "training",
    reward_override: dict[str, float] | None = None,
) -> Path:
    task = load_task(task_path)
    sandbox = LocalSandbox(FIXTURES / task.repo_id)
    try:
        # Initialise repo state under git so we can compute true diffs.
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "swegraph@example.com"],
            ["git", "config", "user.name", "swegraph"],
            ["git", "add", "."],
            ["git", "commit", "-q", "-m", "init"],
        ):
            subprocess.run(cmd, cwd=sandbox.workspace, capture_output=True)

        api = ActionAPI(sandbox.workspace, sandbox.run)
        _apply_mutation(task, api)
        baseline_snapshot = _snapshot(sandbox.workspace)

        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "task.json").write_text(task_path.read_text(encoding="utf-8"), encoding="utf-8")

        logger = TrajectoryLogger(out_dir / "trajectory.jsonl")
        milestones = MilestoneState(task_started=True)
        reward_cfg = {**DEFAULT_REWARD, **(task.reward_config or {}), **(reward_override or {})}
        reward = RewardTracker(reward_cfg)

        # Initial public-test reading so reward.public_failure_reproduced can fire
        # even before the baseline acts.
        initial_pub = run_pytest(sandbox.workspace, task.public_tests)
        pre_failed = initial_pub["failed"]
        if not initial_pub["all_passed"] and initial_pub["failed"] > 0:
            milestones.public_failure_reproduced = True

        read_files: set[str] = set()
        relevant_files = task.mutation_metadata.get("relevant_files", [])

        steps_log: list[TrajectoryStep] = []

        for i, action in enumerate(BASELINES[baseline](api, task)):
            if action.action_type == "read_file":
                read_files.add(action.args.get("path", ""))

            changed_files = changed_files_from_workspace(sandbox.workspace, baseline_snapshot)

            post_pub: dict[str, Any] | None = None
            if action.action_type in ("write_file", "replace_text", "apply_patch") or (
                action.action_type == "run_command"
                and "pytest" in (action.args.get("command") or "")
            ):
                post_pub = run_pytest(sandbox.workspace, task.public_tests)

            penalties = _update_milestones(
                milestones,
                action=action,
                pre_failed=pre_failed,
                post=post_pub,
                changed_files=changed_files,
                read_files=read_files,
                relevant_files=relevant_files,
                protected_files=task.protected_files,
                public_tests=task.public_tests,
                workspace=sandbox.workspace,
                finished=api.finished,
            )
            comp = reward.step(milestones, penalties)
            step = _action_to_step(
                step_index=i,
                action=action,
                pre_pub=initial_pub,
                post_pub=post_pub,
                changed_files=changed_files,
                milestones=milestones,
                reward_components=comp,
                cumulative_reward=reward.total,
            )
            logger.add(step)
            steps_log.append(step)

        # Final hidden-test eval. In training mode this also flips the
        # hidden_tests_pass milestone and awards its reward; in benchmark mode
        # the reward is withheld until eval time.
        hidden_status = run_hidden_tests(sandbox.workspace, task.hidden_tests)
        if mode == "training" and steps_log:
            milestones.hidden_tests_pass = hidden_status["all_passed"]
            comp = reward.step(milestones, {})
            last = steps_log[-1]
            last.milestone_state = milestones.__dict__.copy()
            last.reward_components = {**last.reward_components, **{
                k: v for k, v in comp.items() if not k.startswith("_") or k == "_step_total"
            }}
            last.reward_components["_step_total"] = (
                last.reward_components.get("_step_total", 0.0) + comp.get("_step_total", 0.0)
            )
            last.reward_components["_cumulative"] = reward.total
            last.cumulative_reward = reward.total

        report = evaluate_run(
            task,
            sandbox.workspace,
            baseline_snapshot,
            len(logger.steps),
            reward.total,
            milestones,
            read_files=read_files,
            hidden_status=hidden_status,
        )
        save_report(report, out_dir / "final_report.json")

        diff = _git(sandbox.workspace, "diff").stdout
        (out_dir / "patch.diff").write_text(diff, encoding="utf-8")
        (out_dir / "run.log").write_text(
            (initial_pub["output"] or "") + "\n---\n" + (hidden_status["output"] or ""),
            encoding="utf-8",
        )
        _write_replay(out_dir, task, steps_log, report)
        return out_dir
    finally:
        sandbox.teardown()


def cmd_generate(args):
    reward_cfg = load_reward_config(Path(args.reward_config)) if args.reward_config else None
    generate_tasks(args.num_tasks, Path(args.out), seed=args.seed, reward_config=reward_cfg)


def cmd_run(args):
    reward_cfg = load_reward_config(Path(args.reward_config)) if args.reward_config else None
    run_task(Path(args.task), args.baseline, Path(args.out), mode=args.mode, reward_override=reward_cfg)


def cmd_eval(args):
    run_dir = Path(args.run)
    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    print(json.dumps(report, indent=2))


def cmd_batch(args):
    tasks = sorted(Path(args.tasks).glob("task_*.json"))
    out_root = Path(args.out)
    if out_root.exists() and args.clean:
        shutil.rmtree(out_root)
    reward_cfg = load_reward_config(Path(args.reward_config)) if args.reward_config else None
    summary = []
    for t in tasks:
        run_task(t, args.baseline, out_root / t.stem, mode=args.mode, reward_override=reward_cfg)
        report = json.loads((out_root / t.stem / "final_report.json").read_text())
        summary.append(
            {
                "task_id": report["task_id"],
                "public": report["public_tests_pass"],
                "hidden": report["hidden_tests_pass"],
                "success": report["final_success"],
                "reward": report["reward_total"],
            }
        )
    (out_root / "batch_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(prog="swegraph")
    sp = p.add_subparsers(dest="cmd", required=True)

    g = sp.add_parser("generate")
    g.add_argument("--out", default="runs/tasks")
    g.add_argument("--num-tasks", type=int, default=30)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--reward-config", default=None)
    g.set_defaults(func=cmd_generate)

    r = sp.add_parser("run")
    r.add_argument("--task", required=True)
    r.add_argument("--baseline", choices=list(BASELINES.keys()), default="oracle")
    r.add_argument("--out", required=True)
    r.add_argument("--mode", choices=["training", "benchmark"], default="training")
    r.add_argument("--reward-config", default=None)
    r.set_defaults(func=cmd_run)

    e = sp.add_parser("eval")
    e.add_argument("--run", required=True)
    e.set_defaults(func=cmd_eval)

    b = sp.add_parser("batch")
    b.add_argument("--tasks", required=True)
    b.add_argument("--baseline", choices=list(BASELINES.keys()), default="do_nothing")
    b.add_argument("--out", required=True)
    b.add_argument("--mode", choices=["training", "benchmark"], default="training")
    b.add_argument("--clean", action="store_true")
    b.add_argument("--reward-config", default=None)
    b.set_defaults(func=cmd_batch)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
