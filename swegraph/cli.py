from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from swegraph.actions import ActionAPI
from swegraph.baselines import BASELINES
from swegraph.evaluator import evaluate_run, save_report
from swegraph.reward import RewardTracker
from swegraph.sandbox import LocalSandbox
from swegraph.schema import MilestoneState, TrajectoryStep, utc_now_iso
from swegraph.task import generate_tasks, load_task
from swegraph.tests_runner import run_pytest
from swegraph.trajectory import TrajectoryLogger
from swegraph.utils.diffing import changed_files_from_workspace


FIXTURES = Path(__file__).parent / "fixtures" / "repos"


def _snapshot(workspace: Path) -> dict[str, str]:
    snap = {}
    for p in workspace.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            snap[str(p.relative_to(workspace))] = p.read_text(encoding="utf-8", errors="ignore")
    return snap


def _apply_mutation(task, api: ActionAPI) -> None:
    mm = task.mutation_metadata
    if mm.get("type") == "replace_text":
        api.replace_text(mm["path"], mm["old"], mm["new"])


def run_task(task_path: Path, baseline: str, out_dir: Path, mode: str = "training") -> Path:
    task = load_task(task_path)
    sandbox = LocalSandbox(FIXTURES / task.repo_id)
    try:
        __import__("subprocess").run(["git", "init"], cwd=sandbox.workspace, capture_output=True)
        __import__("subprocess").run(["git", "config", "user.email", "swegraph@example.com"], cwd=sandbox.workspace, capture_output=True)
        __import__("subprocess").run(["git", "config", "user.name", "swegraph"], cwd=sandbox.workspace, capture_output=True)
        __import__("subprocess").run(["git", "add", "."], cwd=sandbox.workspace, capture_output=True)
        __import__("subprocess").run(["git", "commit", "-m", "init"], cwd=sandbox.workspace, capture_output=True)
        api = ActionAPI(sandbox.workspace, sandbox.run)
        _apply_mutation(task, api)
        baseline_snapshot = _snapshot(sandbox.workspace)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "task.json").write_text(task_path.read_text(encoding="utf-8"), encoding="utf-8")
        logger = TrajectoryLogger(out_dir / "trajectory.jsonl")
        milestones = MilestoneState(task_started=True)
        reward = RewardTracker(task.reward_config)
        pre = run_pytest(sandbox.workspace, task.public_tests)
        if not pre["all_passed"]:
            milestones.public_failure_reproduced = True
        BASELINES[baseline](api, task)
        changed = changed_files_from_workspace(sandbox.workspace, baseline_snapshot)
        milestones.implementation_edited = any(f.endswith(".py") and "/test" not in f for f in changed)
        milestones.relevant_file_read = True
        post = run_pytest(sandbox.workspace, task.public_tests)
        if post["failed"] < pre["failed"]:
            milestones.public_tests_improved = True
        milestones.public_tests_pass = post["all_passed"]
        if mode == "training":
            from swegraph.tests_runner import run_hidden_tests

            milestones.hidden_tests_pass = run_hidden_tests(sandbox.workspace, task.hidden_tests)["all_passed"]
        milestones.final_submitted = api.finished
        penalties = {}
        comp = reward.step(milestones, penalties)
        step = TrajectoryStep(
            timestamp=utc_now_iso(),
            step_index=0,
            action_type=f"baseline:{baseline}",
            command="python -m pytest -q tests",
            stdout_summary=post["output"][-300:],
            stderr_summary="",
            exit_code=post["exit_code"],
            changed_files=changed,
            public_test_status=post,
            milestone_state=milestones.__dict__,
            reward_components=comp,
            cumulative_reward=reward.total,
        )
        logger.add(step)
        report = evaluate_run(task, sandbox.workspace, baseline_snapshot, len(logger.steps), reward.total, milestones)
        save_report(report, out_dir / "final_report.json")
        diff = __import__("subprocess").run(["git", "diff"], cwd=sandbox.workspace, capture_output=True, text=True).stdout
        (out_dir / "patch.diff").write_text(diff, encoding="utf-8")
        (out_dir / "run.log").write_text(post["output"], encoding="utf-8")
        (out_dir / "replay.md").write_text(f"# Replay\n\nPrompt: {task.user_prompt}\n\nSteps: {len(logger.steps)}\n", encoding="utf-8")
        return out_dir
    finally:
        sandbox.teardown()


def cmd_generate(args):
    generate_tasks(args.num_tasks, Path(args.out), seed=args.seed)


def cmd_run(args):
    run_task(Path(args.task), args.baseline, Path(args.out), mode=args.mode)


def cmd_eval(args):
    run_dir = Path(args.run)
    report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    print(json.dumps(report, indent=2))


def cmd_batch(args):
    tasks = sorted(Path(args.tasks).glob("task_*.json"))
    out_root = Path(args.out)
    if out_root.exists() and args.clean:
        shutil.rmtree(out_root)
    for t in tasks:
        run_task(t, args.baseline, out_root / t.stem, mode=args.mode)


def main():
    p = argparse.ArgumentParser(prog="swegraph")
    sp = p.add_subparsers(dest="cmd", required=True)

    g = sp.add_parser("generate")
    g.add_argument("--out", default="runs/tasks")
    g.add_argument("--num-tasks", type=int, default=30)
    g.add_argument("--seed", type=int, default=7)
    g.set_defaults(func=cmd_generate)

    r = sp.add_parser("run")
    r.add_argument("--task", required=True)
    r.add_argument("--baseline", choices=list(BASELINES.keys()), default="oracle")
    r.add_argument("--out", required=True)
    r.add_argument("--mode", choices=["training", "benchmark"], default="training")
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
    b.set_defaults(func=cmd_batch)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
