from __future__ import annotations

from typing import Iterator


def run_do_nothing(api, task) -> Iterator:
    """Baseline that observes but never edits.

    Should fail almost every generated task while still producing a
    well-formed trajectory log (useful as a lower bound + reward sanity check).
    """
    from swegraph.baselines import Action

    res = api.run_command("python -m pytest -q tests")
    yield Action(
        "run_command",
        {
            "command": "python -m pytest -q tests",
            "exit_code": res["exit_code"],
            "stdout_summary": res["stdout"][-300:],
            "stderr_summary": res["stderr"][-300:],
        },
        "list current test status",
    )
    api.finish()
    yield Action("finish", {}, "no edits attempted")
