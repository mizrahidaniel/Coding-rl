from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
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
from swegraph.tests_runner import run_pytest
from swegraph.trajectory import TrajectoryLogger
from swegraph.utils.diffing import changed_files_from_workspace
from swegraph.utils.file_guard import collect_guard_hits
from swegraph.validators import (
    ValidationResult,
    all_passed,
    coerce_legacy_hidden_tests,
    run_validators,
)


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
    """Apply the task's mutation to the workspace.

    When ``mutation_metadata`` carries explicit ``line`` and ``col`` (as the
    v3 ingest pipeline emits), apply the substitution precisely. Without
    those fields we fall back to the global ``str.replace`` form that v1/v2
    hand-authored tasks expect.
    """
    from swegraph.ingest.mutators import replace_at_line_col

    mm = task.mutation_metadata
    if mm.get("type") != "replace_text":
        return
    if "line" in mm and "col" in mm:
        replace_at_line_col(
            api.workspace / mm["path"],
            int(mm["line"]),
            int(mm["col"]),
            mm["old"],
            mm["new"],
        )
    else:
        api.replace_text(mm["path"], mm["old"], mm["new"])


def _is_implementation_file(path: str) -> bool:
    return (
        path.endswith(".py")
        and not path.startswith("tests/")
        and "/tests/" not in path
        and not path.endswith("conftest.py")
    )


def _gz_b64(text: str) -> str:
    if not text:
        return ""
    return base64.b64encode(gzip.compress(text.encode("utf-8"))).decode("ascii")


def _milestone_diff(prev: dict, curr: dict) -> dict[str, bool]:
    return {k: v for k, v in curr.items() if prev.get(k) != v}


def _update_milestones(
    milestones: MilestoneState,
    *,
    action: Action,
    pre_failed: int,
    post: dict[str, Any] | None,
    changed_files: list[str],
    read_files: set[str],
    relevant_files: list[str],
    root_cause_file: str | None,
    protected_files: list[str],
    public_tests: list[str],
    workspace: Path,
    finished: bool,
    write_count_so_far: int,
    baseline_snapshot: dict[str, str],
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
        # localization_correct: if the task has a known root_cause_file, the
        # agent must have read it BEFORE its first write.
        if root_cause_file is not None and write_count_so_far == 1:
            if root_cause_file not in read_files:
                milestones.localization_correct = False

    if post is not None:
        if not milestones.public_failure_reproduced and post["failed"] > 0:
            milestones.public_failure_reproduced = True
        if post["failed"] < pre_failed:
            milestones.public_tests_improved = True
        milestones.public_tests_pass = post["all_passed"]

    # Guards (recomputed every step so penalties trigger as soon as something
    # bad happens, not only at final eval).
    guard_hits = collect_guard_hits(
        workspace,
        public_tests=public_tests,
        changed_files=changed_files,
        baseline_snapshot=baseline_snapshot,
    )
    protected_changed = [f for f in changed_files if f in protected_files]
    if protected_changed:
        milestones.protected_files_unchanged = False
        penalties["unrelated_files_changed"] = -0.2
    if any(h.severity == "block" for h in guard_hits):
        milestones.no_test_deletion = False
        penalties["tests_deleted"] = -0.5

    if finished:
        milestones.final_submitted = True
    return penalties


def _action_to_step(
    *,
    step_index: int,
    action: Action,
    post_pub: dict[str, Any] | None,
    changed_files: list[str],
    milestones: MilestoneState,
    prev_milestones: dict,
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
    full_stdout = action.args.get("full_stdout")
    full_stderr = action.args.get("full_stderr")
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
        stdout_full_b64=_gz_b64(full_stdout or ""),
        stderr_full_b64=_gz_b64(full_stderr or ""),
        per_test_status=(post_pub or {}).get("per_test_status", {}) or {},
        milestone_delta=_milestone_diff(prev_milestones, milestones.__dict__),
    )


def _write_replay(out_dir: Path, task, steps: list[TrajectoryStep], final_report) -> None:
    lines = [
        f"# Replay: {task.task_id} ({task.task_family} on {task.repo_id})",
        "",
        f"**User prompt:** {task.user_prompt}",
        "",
        f"**Hidden spec:** {task.hidden_formal_spec}",
        "",
    ]
    if final_report.causal_hop_metadata:
        m = final_report.causal_hop_metadata
        lines += [
            f"**Causal hops:** {m.get('import_hops')}  ",
            f"**Root cause file:** `{m.get('root_cause_file')}`  ",
            f"**Localization correct:** {m.get('localization_correct')}",
            "",
        ]
    lines += [
        "## Steps",
        "",
        "| # | action | summary | tests passed/failed | reward Δ | cum |",
        "| - | ------ | ------- | ------------------- | -------- | --- |",
    ]
    for s in steps:
        summary = s.command or ""
        if s.action_type in ("read_file", "write_file", "replace_text") and s.edit_metadata:
            summary = (s.edit_metadata.get("path", "") + " " + s.edit_metadata.get("note", "")).strip()
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
        "## Validator results",
        "",
    ]
    for v in final_report.validator_results:
        passed = "x" if v.get("passed") else " "
        lines.append(f"- [{passed}] **{v.get('kind')}** — {v.get('detail', '')}")
    lines += [
        "",
        "## Guard report",
        "",
    ]
    if final_report.guard_report:
        for h in final_report.guard_report:
            lines.append(f"- `{h.get('rule')}` ({h.get('severity')}) {h.get('file') or ''} {h.get('detail') or ''}")
    else:
        lines.append("_clean_")
    lines += [
        "",
        "## Final report",
        "",
        f"- public tests pass: **{final_report.public_tests_pass}**",
        f"- hidden tests pass: **{final_report.hidden_tests_pass}**",
        f"- final success: **{final_report.final_success}**",
        f"- protected files changed: {final_report.protected_files_changed or 'none'}",
        f"- tests deleted/disabled or guard-blocked: {final_report.tests_deleted_or_disabled}",
        f"- unrelated files changed: {final_report.unrelated_files_changed or 'none'}",
        f"- relevant files inspected: {final_report.relevant_files_inspected}",
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
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "swegraph@example.com"],
            ["git", "config", "user.name", "swegraph"],
            ["git", "add", "."],
            ["git", "commit", "-q", "-m", "init"],
        ):
            subprocess.run(cmd, cwd=sandbox.workspace, capture_output=True)

        api = ActionAPI(sandbox.workspace, sandbox.run)
        # v3: ingested tasks may override the public-test files that ship in
        # the fixture. Apply overrides BEFORE the mutation so the public set
        # is the partition we declared at ingest time, not the full original
        # suite.
        if task.public_test_overrides:
            # Wipe original tests so leftovers don't pollute the public
            # surface, then write only the overrides we authored.
            tests_dir = sandbox.workspace / "tests"
            if tests_dir.exists():
                for p in tests_dir.rglob("test_*.py"):
                    try:
                        p.unlink()
                    except OSError:
                        pass
            for rel, body in task.public_test_overrides.items():
                target = sandbox.workspace / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
        _apply_mutation(task, api)
        baseline_snapshot = _snapshot(sandbox.workspace)

        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "task.json").write_text(task_path.read_text(encoding="utf-8"), encoding="utf-8")

        logger = TrajectoryLogger(out_dir / "trajectory.jsonl")
        milestones = MilestoneState(task_started=True)
        prev_milestone_snapshot = milestones.__dict__.copy()

        reward_cfg = {**DEFAULT_REWARD, **(task.reward_config or {}), **(reward_override or {})}
        reward = RewardTracker(reward_cfg)

        initial_pub = run_pytest(sandbox.workspace, task.public_tests)
        pre_failed = initial_pub["failed"]
        if not initial_pub["all_passed"] and initial_pub["failed"] > 0:
            milestones.public_failure_reproduced = True

        read_files: set[str] = set()
        relevant_files = task.mutation_metadata.get("relevant_files", [])
        root_cause_file = task.mutation_metadata.get("root_cause_file")
        write_count = 0

        steps_log: list[TrajectoryStep] = []

        for i, action in enumerate(BASELINES[baseline](api, task)):
            if action.action_type == "read_file":
                read_files.add(action.args.get("path", ""))
            if action.action_type in ("write_file", "replace_text", "apply_patch"):
                write_count += 1

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
                root_cause_file=root_cause_file,
                protected_files=task.protected_files,
                public_tests=task.public_tests,
                workspace=sandbox.workspace,
                finished=api.finished,
                write_count_so_far=write_count,
                baseline_snapshot=baseline_snapshot,
            )
            comp = reward.step(milestones, penalties)
            step = _action_to_step(
                step_index=i,
                action=action,
                post_pub=post_pub,
                changed_files=changed_files,
                milestones=milestones,
                prev_milestones=prev_milestone_snapshot,
                reward_components=comp,
                cumulative_reward=reward.total,
            )
            prev_milestone_snapshot = milestones.__dict__.copy()
            logger.add(step)
            steps_log.append(step)

        # Final hidden-validator eval.
        validator_specs = coerce_legacy_hidden_tests({
            "hidden_validators": task.hidden_validators,
            "hidden_tests": task.hidden_tests,
        })
        validator_results = run_validators(sandbox.workspace, validator_specs)
        hidden_pass = all_passed(validator_results)

        if mode == "training" and steps_log:
            milestones.hidden_tests_pass = hidden_pass
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
            validator_results=validator_results,
        )
        save_report(report, out_dir / "final_report.json")

        diff = _git(sandbox.workspace, "diff").stdout
        (out_dir / "patch.diff").write_text(diff, encoding="utf-8")
        (out_dir / "run.log").write_text(
            (initial_pub["output"] or "")
            + "\n--- validators ---\n"
            + json.dumps([r.__dict__ for r in validator_results], indent=2),
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
    _apply_llm_flags(args)
    run_task(Path(args.task), args.baseline, Path(args.out), mode=args.mode, reward_override=reward_cfg)


def _apply_llm_flags(args) -> None:
    """LLM-baseline flags are read by run_llm_baseline via env vars so the
    baseline iterator stays a plain (api, task) -> Iterator function. The CLI
    surfaces them as proper flags and pushes them into the env."""
    if getattr(args, "llm_model", None):
        os.environ["SWEGRAPH_LLM_MODEL"] = args.llm_model
    if getattr(args, "llm_max_steps", None):
        os.environ["SWEGRAPH_LLM_MAX_STEPS"] = str(args.llm_max_steps)
    if getattr(args, "llm_effort", None):
        os.environ["SWEGRAPH_LLM_EFFORT"] = args.llm_effort


def cmd_eval(args):
    run_dir = Path(args.run)
    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    print(json.dumps(report, indent=2))


def cmd_batch(args):
    _apply_llm_flags(args)
    tasks_dir = Path(args.tasks)
    tasks = sorted(tasks_dir.glob("task_*.json")) + sorted(tasks_dir.glob("ingest_task_*.json"))
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
                "guard_hits": len(report.get("guard_report", [])),
                "import_hops": report.get("causal_hop_metadata", {}).get("import_hops"),
                "localization_correct": report.get("causal_hop_metadata", {}).get("localization_correct"),
            }
        )
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "batch_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def cmd_batch_prm(args):
    """Emit paired (state, oracle_action, counterfactual_action) preference
    tuples for PRM training. See ``swegraph/prm.py``.
    """
    from swegraph.prm import emit_prm_pairs

    tasks = sorted(Path(args.tasks).glob("task_*.json")) + sorted(Path(args.tasks).glob("ingest_task_*.json"))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    baselines = [b.strip() for b in args.baselines.split(",") if b.strip()]
    if "oracle" not in baselines:
        baselines = ["oracle", *baselines]
    emit_prm_pairs(tasks=tasks, baselines=baselines, run_root=Path(args.runs_dir), out_path=out_path)


def cmd_ingest(args):
    """Procedurally ingest a real (or vendored-real) fixture into a set of
    SWEGraph tasks via AST mutations + public/hidden test split. See
    ``swegraph/ingest/task_factory.py``.
    """
    from swegraph.ingest import build_ingested_tasks
    from swegraph.reward import load_reward_config

    fixture_dir = FIXTURES / args.fixture
    if not fixture_dir.exists():
        # Allow absolute or workspace-relative paths too.
        cand = Path(args.fixture)
        if cand.exists():
            fixture_dir = cand
        else:
            raise FileNotFoundError(f"fixture not found: {args.fixture}")
    reward_cfg = load_reward_config(Path(args.reward_config)) if args.reward_config else None
    paths = build_ingested_tasks(
        fixture_dir=fixture_dir,
        out_dir=Path(args.out),
        seed=args.seed,
        hidden_frac=args.hidden_frac,
        max_tasks=args.max_tasks,
        operators=[op.strip() for op in args.operators.split(",")] if args.operators else None,
        timeout=args.timeout,
        reward_config=reward_cfg,
    )
    print(f"emitted {len(paths)} ingested tasks under {args.out}")


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
    r.add_argument("--llm-model", default=None, help="Override the model used by the `llm` baseline (default claude-opus-4-7)")
    r.add_argument("--llm-max-steps", type=int, default=None, help="Override the per-task LLM step budget (default 30)")
    r.add_argument("--llm-effort", choices=["low", "medium", "high", "xhigh", "max"], default=None, help="Override the LLM effort level (default high)")
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
    b.add_argument("--llm-model", default=None)
    b.add_argument("--llm-max-steps", type=int, default=None)
    b.add_argument("--llm-effort", choices=["low", "medium", "high", "xhigh", "max"], default=None)
    b.set_defaults(func=cmd_batch)

    bp = sp.add_parser("batch-prm")
    bp.add_argument("--tasks", required=True)
    bp.add_argument("--runs-dir", required=True, help="root containing per-baseline run dirs (e.g. runs/)")
    bp.add_argument("--baselines", required=True, help="comma-separated baseline names; oracle always included")
    bp.add_argument("--out", required=True, help="output JSONL path for preference pairs")
    bp.set_defaults(func=cmd_batch_prm)

    ig = sp.add_parser("ingest", help="generate tasks from a real-or-vendored fixture via AST mutators")
    ig.add_argument("--fixture", required=True, help="fixture name under swegraph/fixtures/repos/ or absolute path")
    ig.add_argument("--out", required=True, help="output dir for ingested task JSON")
    ig.add_argument("--seed", type=int, default=7)
    ig.add_argument("--hidden-frac", type=float, default=0.3, help="fraction of test functions held out as hidden")
    ig.add_argument("--max-tasks", type=int, default=20)
    ig.add_argument("--operators", default=None, help="comma-separated mutator names (default: all)")
    ig.add_argument("--timeout", type=int, default=30)
    ig.add_argument("--reward-config", default=None)
    ig.set_defaults(func=cmd_ingest)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
