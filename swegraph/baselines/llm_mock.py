"""Scripted-responder mock for the LLM baseline.

Used by tests and for offline reproductions. The mock builds a canned
sequence of ``tool_use`` responses that mimics what a competent model would
do on the standard SWEGraph task families:

  reproduce -> read root_cause_file -> apply oracle reverse_mutation -> verify -> finish

This is intentionally close to the oracle baseline. The point isn't to
demonstrate intelligence — it's to exercise the LLM tool-use loop end to end
without an API key, so the rest of the harness can be tested.

For a *real* mock that emits something resembling an LLM trajectory but
diverges from oracle (so PRM data has variety), use a custom responder via
``run_llm_loop(..., responder=my_mock)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from swegraph.baselines.llm_adapter import LLMConfig, run_llm_loop


@dataclass
class _ToolUseBlock:
    type: str
    id: str
    name: str
    input: dict


@dataclass
class _TextBlock:
    type: str
    text: str


@dataclass
class _MockResponse:
    stop_reason: str
    content: list


def _scripted_responder_for(task):
    """Build a responder that emits a fixed sequence of tool calls.

    The script is generated from the task's ``mutation_metadata`` /
    ``oracle_metadata`` so it works across families (bug_injection,
    config_bug, feature_addition, causal_hop, real_repo_ingested).
    """
    mm = task.mutation_metadata or {}
    om = task.oracle_metadata or {}
    relevant_files = mm.get("relevant_files", [])
    public_test_cmd = "python -m pytest -q " + " ".join(task.public_tests or ["tests"])

    script: list[dict] = []
    sid = [0]

    def _next_id():
        sid[0] += 1
        return f"toolu_mock_{sid[0]:03d}"

    def _push(name: str, args: dict):
        script.append({"name": name, "input": args})

    # 1. reproduce
    _push("run_command", {"command": public_test_cmd})
    # 2. read each relevant file
    for rf in relevant_files[:5]:
        _push("read_file", {"path": rf})
    # 3. apply the oracle patch
    if om.get("patch_type") == "reverse_mutation" and "old" in mm and "new" in mm:
        _push("replace_text", {"path": mm["path"], "old": mm["new"], "new": mm["old"]})
    elif om.get("patch_type") == "replace_text":
        _push("replace_text", {"path": om["path"], "old": om["old"], "new": om["new"]})
    # 4. verify
    _push("run_command", {"command": public_test_cmd})
    # 5. finish
    _push("finish", {})

    cursor = [0]

    def responder(_messages):
        if cursor[0] >= len(script):
            # Out of script; emit no tool calls so the loop terminates.
            return _MockResponse(
                stop_reason="end_turn",
                content=[_TextBlock("text", "(script exhausted)")],
            )
        entry = script[cursor[0]]
        cursor[0] += 1
        block = _ToolUseBlock("tool_use", _next_id(), entry["name"], entry["input"])
        return _MockResponse(stop_reason="tool_use", content=[block])

    return responder


def run_llm_mock_baseline(api, task) -> Iterator:
    """Baseline registration: drives ``run_llm_loop`` with a scripted mock."""
    cfg = LLMConfig(model="mock", max_steps=30)
    responder = _scripted_responder_for(task)
    yield from run_llm_loop(api, task, cfg, responder=responder)
