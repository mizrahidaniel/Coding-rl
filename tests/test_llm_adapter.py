"""Tests for the LLM-driven baseline.

Three layers:
1. Unit tests on ``execute_tool_call`` — translation from Claude tool calls
   to ``Action`` records is the most failure-prone seam, so it's tested
   directly.
2. End-to-end test using the scripted-mock baseline (``llm_mock``) — runs
   the whole loop on a real task without an API key.
3. An integration test gated on ANTHROPIC_API_KEY for real-Claude smoke
   testing; skipped by default so CI stays free.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from swegraph.actions import ActionAPI
from swegraph.baselines.llm_adapter import (
    LLMConfig,
    execute_tool_call,
    run_llm_loop,
)
from swegraph.cli import run_task
from swegraph.task import generate_tasks


# --- Layer 1: tool-call -> Action mapping ----------------------------------


class _RecordingAPI:
    """Minimal ActionAPI stand-in for unit tests."""

    def __init__(self, tmp_path: Path):
        self.workspace = tmp_path
        self.finished = False
        self.calls: list[tuple[str, tuple]] = []

    def run_command(self, cmd: str) -> dict:
        self.calls.append(("run_command", (cmd,)))
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    def read_file(self, path: str) -> str:
        self.calls.append(("read_file", (path,)))
        return (self.workspace / path).read_text()

    def write_file(self, path: str, content: str) -> None:
        self.calls.append(("write_file", (path, content)))
        (self.workspace / path).parent.mkdir(parents=True, exist_ok=True)
        (self.workspace / path).write_text(content)

    def replace_text(self, path: str, old: str, new: str) -> bool:
        self.calls.append(("replace_text", (path, old, new)))
        p = self.workspace / path
        if not p.exists():
            return False
        text = p.read_text()
        if old not in text:
            return False
        p.write_text(text.replace(old, new))
        return True

    def finish(self) -> None:
        self.calls.append(("finish", ()))
        self.finished = True


def test_run_command_emits_run_command_action(tmp_path: Path):
    api = _RecordingAPI(tmp_path)
    action, result_text = execute_tool_call("run_command", {"command": "echo hi"}, api)
    assert action.action_type == "run_command"
    assert action.args["command"] == "echo hi"
    assert "exit_code=0" in result_text


def test_read_file_returns_truncated_content(tmp_path: Path):
    api = _RecordingAPI(tmp_path)
    big = "x" * 10000
    (tmp_path / "big.py").write_text(big)
    action, result_text = execute_tool_call("read_file", {"path": "big.py"}, api)
    assert action.action_type == "read_file"
    assert action.args["path"] == "big.py"
    # Truncated; both head and tail markers present
    assert "truncated" in result_text


def test_read_file_handles_missing(tmp_path: Path):
    api = _RecordingAPI(tmp_path)
    action, result_text = execute_tool_call("read_file", {"path": "nope.py"}, api)
    assert action.args.get("error") == "not_found"
    assert "not found" in result_text.lower()


def test_replace_text_no_match_returns_explainable_error(tmp_path: Path):
    api = _RecordingAPI(tmp_path)
    (tmp_path / "f.py").write_text("hello")
    action, result_text = execute_tool_call(
        "replace_text", {"path": "f.py", "old": "missing", "new": "x"}, api
    )
    assert action.args["matched"] is False
    assert "NO MATCH" in result_text


def test_finish_marks_api_finished(tmp_path: Path):
    api = _RecordingAPI(tmp_path)
    action, _ = execute_tool_call("finish", {}, api)
    assert action.action_type == "finish"
    assert api.finished


def test_unknown_tool_surfaces_error_to_model(tmp_path: Path):
    api = _RecordingAPI(tmp_path)
    action, result_text = execute_tool_call("teleport", {}, api)
    assert "Unknown tool" in result_text


# --- Layer 2: end-to-end via llm_mock --------------------------------------


def _report(out_dir: Path) -> dict:
    return json.loads((out_dir / "final_report.json").read_text())


def test_llm_mock_solves_bug_injection(tmp_path: Path):
    """The scripted mock should solve every task family the oracle solves;
    confirms the LLM tool-use loop wires through the trajectory logger
    correctly."""
    tasks = generate_tasks(4, tmp_path / "tasks", seed=11)
    successes = 0
    for t in tasks:
        run_task(t, "llm_mock", tmp_path / "runs" / t.stem)
        report = _report(tmp_path / "runs" / t.stem)
        successes += int(report["hidden_tests_pass"])
    assert successes == len(tasks)


def test_llm_mock_emits_multi_step_trajectory(tmp_path: Path):
    task = generate_tasks(1, tmp_path / "tasks", seed=2)[0]
    out = tmp_path / "run"
    run_task(task, "llm_mock", out)
    lines = (out / "trajectory.jsonl").read_text().strip().splitlines()
    assert len(lines) >= 4
    types = [json.loads(line)["action_type"] for line in lines]
    assert types[0] == "run_command"
    assert types[-1] == "finish"
    assert "read_file" in types


def test_llm_loop_step_budget_terminates_cleanly(tmp_path: Path):
    """Drive run_llm_loop with a responder that never emits ``finish`` to
    confirm the step-budget path produces a clean trajectory close."""
    from swegraph.baselines.llm_mock import _ToolUseBlock, _MockResponse

    task = generate_tasks(1, tmp_path / "tasks", seed=5)[0]
    spec = json.loads(task.read_text())

    # Mock that emits a single read_file tool call forever.
    tu_id = [0]

    def responder(_messages):
        tu_id[0] += 1
        block = _ToolUseBlock(
            "tool_use", f"toolu_{tu_id[0]:03d}", "read_file",
            {"path": spec["mutation_metadata"]["root_cause_file"]},
        )
        return _MockResponse(stop_reason="tool_use", content=[block])

    # Drive the loop directly, capturing actions.
    from swegraph.sandbox import LocalSandbox
    fixtures = Path(__file__).resolve().parents[1] / "swegraph" / "fixtures" / "repos"
    sandbox = LocalSandbox(fixtures / spec["repo_id"])
    try:
        api = ActionAPI(sandbox.workspace, sandbox.run)
        cfg = LLMConfig(model="mock", max_steps=3)
        actions = list(run_llm_loop(api, type("T", (), spec)(), cfg, responder=responder))
        # 3 read_file actions + 1 step_budget_exhausted finish
        assert len(actions) == 4
        assert actions[-1].action_type == "finish"
        assert actions[-1].args.get("reason") == "step_budget_exhausted"
    finally:
        sandbox.teardown()


# --- Layer 3: real-Claude integration (gated) ------------------------------


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set; skipping real-Claude integration test.",
)
def test_real_llm_baseline_smoke(tmp_path: Path):
    """Real Claude rollout, gated. Costs API credits — not run in CI."""
    task = generate_tasks(1, tmp_path / "tasks", seed=42)[0]
    out = tmp_path / "run"
    # Cap steps tightly to keep cost bounded if the test is run.
    os.environ["SWEGRAPH_LLM_MAX_STEPS"] = "10"
    try:
        run_task(task, "llm", out)
    finally:
        os.environ.pop("SWEGRAPH_LLM_MAX_STEPS", None)
    report = _report(out)
    # We don't assert success — the test exists to prove the loop works
    # against a real model. We do assert the trajectory was non-trivial.
    assert report["trajectory_length"] >= 1
