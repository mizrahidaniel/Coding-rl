"""LLM-driven baseline: a real coding agent built on the Anthropic SDK.

This is the v4 piece the v3 plan flagged as "table-stakes shim, separate
session." It turns SWEGraph from a harness with three scripted baselines into
a harness any LLM agent can be measured against.

Design choices
- Direct SDK use (`anthropic.Anthropic`) — not the beta tool runner — so the
  outer loop can yield ``Action`` records into the existing trajectory logger
  step by step. The runner already handles snapshot management, milestone
  tracking, and reward; the agent only needs to emit actions.
- ``claude-opus-4-7`` with adaptive thinking and ``effort: "high"`` by default.
  Effort matters more on 4.7 than on any prior Opus model — high is the
  recommended floor for intelligence-sensitive coding work. (See
  shared/model-migration.md.)
- Prompt caching on the (frozen) system prompt so repeated batch runs on the
  same task family are cheap.
- A ``responder`` hook so unit tests can drive the loop without an API key
  (used by ``llm_mock``).

Cost note
- Real LLM rollouts cost real money. Each task is a multi-turn loop with
  thinking enabled, so a single rollout on Opus 4.7 typically runs into the
  low five figures of tokens. Use ``--max-steps`` to cap aggressively when
  iterating, run on small task subsets first, and prefer ``llm_mock`` for
  CI / regression tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterator


SYSTEM_PROMPT = """You are SWEGraph's software-engineering agent. You operate inside an isolated Python workspace and must restore the codebase to a state where the hidden test suite passes.

You have five tools. Use them surgically.

- run_command(command): run a shell command (typically `python -m pytest -q tests` to reproduce or verify).
- read_file(path): read a workspace file. Always read source files before editing them.
- write_file(path, content): replace a file's full contents.
- replace_text(path, old, new): make a precise textual replacement. Prefer this over write_file for small edits — it preserves surrounding code.
- finish(): submit your final answer. Only call after you have verified the public tests pass.

Workflow guidance (recommended, not enforced):
1. Run the public tests with run_command to reproduce the failure mode.
2. Read the source files most likely to contain the bug. The user prompt and any failing-test traceback will hint at what to inspect.
3. Apply the smallest possible patch. Boundary-bug, off-by-one, or missing-condition fixes are usually the right shape.
4. Re-run the public tests with run_command to verify. If still red, iterate.
5. Call finish() exactly once when you believe the implementation is correct.

Hard constraints:
- DO NOT edit files under tests/ or any conftest.py — the harness will detect it and fail you.
- DO NOT modify pytest.ini, pyproject.toml, or setup.cfg.
- DO NOT delete tests, comment out assertions, or insert `assert True` placeholders.
- DO NOT introduce mocks (`unittest.mock`, `pytest_mock`) into test files.
- DO NOT write symlinks.
- Keep edits minimal and inside the source modules under test.

You will be measured on whether the hidden test suite (which you cannot see) passes. The public tests are a useful but incomplete signal — passing them is necessary but not sufficient. If your patch only makes the public tests pass by special-casing their inputs, the hidden tests will fail.
"""


TOOLS: list[dict[str, Any]] = [
    {
        "name": "run_command",
        "description": "Run a shell command in the workspace. Returns exit code, stdout, and stderr. Use this to run pytest, list files, etc. Times out at 30 seconds.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "Shell command to execute."}},
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read a workspace file by relative path. Returns up to ~4000 trailing characters when the file is large.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Workspace-relative path."}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": "Overwrite a workspace file's full contents. Use replace_text for small edits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "replace_text",
        "description": "Replace the first occurrence of `old` with `new` in `path`. Returns whether the replacement matched. Prefer over write_file for surgical edits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
            "additionalProperties": False,
        },
    },
    {
        "name": "finish",
        "description": "Submit your patch. Only call once you've verified the public tests pass.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


@dataclass
class LLMConfig:
    model: str = "claude-opus-4-7"
    max_steps: int = 30
    max_tokens_per_turn: int = 16000
    effort: str = "high"  # low | medium | high | xhigh | max
    enable_thinking: bool = True


def _user_prompt_for_task(task) -> str:
    relevant = task.mutation_metadata.get("relevant_files", [])
    chain_hint = ""
    if "import_hops" in task.mutation_metadata:
        chain_hint = (
            f"\n\nNOTE: This is a causal-hop task. The root cause is "
            f"{task.mutation_metadata['import_hops']} import edge(s) away from the "
            "public test surface — you'll have to chase the import chain to find it."
        )
    public_tests = ", ".join(task.public_tests) if task.public_tests else "(none)"
    relevant_str = ", ".join(relevant) if relevant else "(unspecified)"
    return (
        f"# Task\n\n{task.user_prompt}\n\n"
        f"# Workspace\n\n"
        f"- Public test command: `python -m pytest -q {public_tests}`\n"
        f"- Suggested files to inspect: {relevant_str}\n"
        f"- Allowed files to edit: {', '.join(task.allowed_files) if task.allowed_files else '(unrestricted under the source dir)'}\n"
        f"- Protected files (do NOT modify): {', '.join(task.protected_files)}"
        f"{chain_hint}\n\n"
        "Begin by reproducing the failure with run_command, then inspect, patch, verify, finish."
    )


# -- tool dispatch -----------------------------------------------------------


def _summarise_pytest_result(result: dict) -> str:
    return (
        f"exit_code={result.get('exit_code')}\n"
        f"--- stdout (tail) ---\n{(result.get('stdout') or '')[-2500:]}\n"
        f"--- stderr (tail) ---\n{(result.get('stderr') or '')[-800:]}"
    )


def execute_tool_call(name: str, args: dict, api) -> tuple:
    """Execute a single tool call and return (Action, tool_result_text).

    The Action gets logged to the trajectory; the tool_result_text becomes the
    ``content`` of the ``user`` message we send back to Claude.
    """
    from swegraph.baselines import Action

    if name == "run_command":
        cmd = args.get("command", "")
        result = api.run_command(cmd)
        action = Action(
            "run_command",
            {
                "command": cmd,
                "exit_code": result["exit_code"],
                "stdout_summary": (result.get("stdout") or "")[-300:],
                "stderr_summary": (result.get("stderr") or "")[-300:],
                "full_stdout": result.get("stdout") or "",
                "full_stderr": result.get("stderr") or "",
            },
            "",
        )
        return action, _summarise_pytest_result(result)

    if name == "read_file":
        path = args.get("path", "")
        try:
            content = api.read_file(path)
        except FileNotFoundError:
            return (
                Action("read_file", {"path": path, "error": "not_found"}, ""),
                f"File not found: {path}",
            )
        action = Action("read_file", {"path": path, "size": len(content)}, "")
        # Cap the content the LLM sees to keep the loop within budget.
        if len(content) <= 4000:
            return action, f"--- {path} ---\n{content}"
        head = content[:1000]
        tail = content[-2500:]
        return action, f"--- {path} (truncated; head + tail) ---\n{head}\n[... truncated ...]\n{tail}"

    if name == "write_file":
        path = args.get("path", "")
        content = args.get("content", "")
        api.write_file(path, content)
        action = Action("write_file", {"path": path, "bytes": len(content)}, "")
        return action, f"Wrote {len(content)} bytes to {path}."

    if name == "replace_text":
        path = args.get("path", "")
        old = args.get("old", "")
        new = args.get("new", "")
        ok = api.replace_text(path, old, new)
        action = Action("replace_text", {"path": path, "matched": ok}, "")
        if not ok:
            return action, f"NO MATCH for `old` in {path}. Read the file again before retrying."
        return action, f"Replaced first occurrence in {path}."

    if name == "finish":
        api.finish()
        return Action("finish", {}, "agent finished"), "Submitted."

    # Unknown tool — surface clearly so the model can recover.
    return (
        Action("run_command", {"command": f"<unknown_tool:{name}>", "exit_code": -1}, ""),
        f"ERROR: Unknown tool `{name}`. Valid tools: run_command, read_file, write_file, replace_text, finish.",
    )


# -- responder hooks ---------------------------------------------------------


def _make_anthropic_responder(config: LLMConfig) -> Callable:
    """Default responder: a real Claude API call.

    The system prompt is marked with cache_control so repeated rollouts in a
    batch share the same cached prefix. Adaptive thinking is on by default;
    set ``enable_thinking=False`` for ablations.
    """
    import anthropic

    client = anthropic.Anthropic()

    def responder(messages: list[dict]):
        kwargs: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens_per_turn,
            "system": [
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            ],
            "tools": TOOLS,
            "messages": messages,
            "output_config": {"effort": config.effort},
        }
        if config.enable_thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        return client.messages.create(**kwargs)

    return responder


# -- main loop ---------------------------------------------------------------


def run_llm_loop(
    api,
    task,
    config: LLMConfig | None = None,
    *,
    responder: Callable | None = None,
) -> Iterator:
    """Drive an LLM tool-use loop and yield Actions for the trajectory logger.

    ``responder`` lets tests inject a stand-in for the Anthropic API call.
    The default is a real claude-opus-4-7 client with adaptive thinking +
    prompt caching on the system prompt.
    """
    cfg = config or LLMConfig()
    resp_fn = responder or _make_anthropic_responder(cfg)

    user_msg = _user_prompt_for_task(task)
    messages: list[dict] = [{"role": "user", "content": user_msg}]

    for step in range(cfg.max_steps):
        response = resp_fn(messages)

        if getattr(response, "stop_reason", None) == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue

        tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

        if not tool_use_blocks:
            # Agent stopped without finish — finalise via api.finish() so the
            # trajectory closes cleanly.
            api.finish()
            from swegraph.baselines import Action

            yield Action(
                "finish",
                {"reason": "stopped_without_finish_call"},
                "agent stopped without invoking finish",
            )
            return

        messages.append({"role": "assistant", "content": response.content})
        tool_results: list[dict] = []
        for tu in tool_use_blocks:
            action, result_text = execute_tool_call(tu.name, tu.input, api)
            yield action
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result_text,
            })
            if api.finished:
                # We hit ``finish``; stop dispatching further tool calls in
                # this turn and exit the loop.
                return
        messages.append({"role": "user", "content": tool_results})

    # Step budget exhausted — finalise.
    if not api.finished:
        api.finish()
        from swegraph.baselines import Action

        yield Action(
            "finish",
            {"reason": "step_budget_exhausted", "max_steps": cfg.max_steps},
            "agent step budget exhausted",
        )


def run_llm_baseline(api, task) -> Iterator:
    """Baseline registration: real LLM with default config.

    Reads ANTHROPIC_API_KEY from the environment via the SDK. To customise
    the model, effort, or step budget, drive ``run_llm_loop`` directly.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Use the `llm_mock` baseline for offline tests, "
            "or export an API key to run a real Claude rollout."
        )
    cfg = LLMConfig(
        model=os.environ.get("SWEGRAPH_LLM_MODEL", "claude-opus-4-7"),
        max_steps=int(os.environ.get("SWEGRAPH_LLM_MAX_STEPS", "30")),
        effort=os.environ.get("SWEGRAPH_LLM_EFFORT", "high"),
    )
    yield from run_llm_loop(api, task, cfg)
