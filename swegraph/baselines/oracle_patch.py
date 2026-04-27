from __future__ import annotations

from typing import Iterator


def run_oracle_patch(api, task) -> Iterator:
    """Upper-bound oracle baseline.

    Uses task.oracle_metadata (hidden during normal agent rollouts) to apply
    the canonical fix. Emits realistic intermediate steps so the trajectory log
    includes a reproduce -> inspect -> patch -> verify -> finish arc.
    """
    from swegraph.baselines import Action

    pre = api.run_command("python -m pytest -q tests")
    yield Action(
        "run_command",
        {
            "command": "python -m pytest -q tests",
            "exit_code": pre["exit_code"],
            "stdout_summary": pre["stdout"][-300:],
            "stderr_summary": pre["stderr"][-300:],
        },
        "reproduce failure",
    )

    for rf in task.mutation_metadata.get("relevant_files", []):
        try:
            text = api.read_file(rf)
        except FileNotFoundError:
            continue
        yield Action("read_file", {"path": rf, "size": len(text)}, "inspect relevant source")

    om = task.oracle_metadata
    patch_type = om.get("patch_type")
    if patch_type == "reverse_mutation":
        mm = task.mutation_metadata
        # Use precise (line, col) replacement when the ingest pipeline
        # provided it, so reverse-mutation doesn't accidentally replace
        # other occurrences of short tokens like ``and`` / ``+`` / ``-``.
        if "line" in mm and "col" in mm:
            from swegraph.ingest.mutators import replace_at_line_col

            ok = replace_at_line_col(
                api.workspace / mm["path"],
                int(mm["line"]),
                int(mm["col"]),
                mm["new"],
                mm["old"],
            )
        else:
            ok = api.replace_text(mm["path"], mm["new"], mm["old"])
        yield Action(
            "replace_text",
            {"path": mm["path"], "matched": ok},
            "revert injected mutation",
        )
    elif patch_type == "replace_text":
        ok = api.replace_text(om["path"], om["old"], om["new"])
        yield Action(
            "replace_text",
            {"path": om["path"], "matched": ok},
            "apply oracle implementation",
        )

    post = api.run_command("python -m pytest -q tests")
    yield Action(
        "run_command",
        {
            "command": "python -m pytest -q tests",
            "exit_code": post["exit_code"],
            "stdout_summary": post["stdout"][-300:],
            "stderr_summary": post["stderr"][-300:],
        },
        "verify fix",
    )
    api.finish()
    yield Action("finish", {}, "submit")
