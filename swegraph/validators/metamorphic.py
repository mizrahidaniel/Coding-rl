"""Metamorphic-relation validator.

Spec format::

    {
      "kind": "metamorphic",
      "module": "stats_utils.core",
      "function": "percentile",
      "strategy": [...],                    # same shape as PropertyValidator
      "relations": [
          "monotonic_in_arg",
          "idempotent_under_call",
          "boundary_extrema",
          "non_increasing_size"
      ],
      "relation_args": {
          "monotonic_in_arg": {"arg_index": 1},
          "boundary_extrema": {"arg_index": 0}
      },
      "max_examples": 100,
      "timeout": 30
    }

The contribution over PropertyValidator is the *library of relations*: a task
generator can declare "this function should be monotonic in its second
argument" without authoring an ``assertion`` Python expression.

Auto-extraction from public-test ASTs (e.g., spotting bounded-output asserts
and turning them into ``boundary_extrema`` relations) lives in
``utils.metamorphic_extract``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


_RUNNER_MODULE = "swegraph.validators._runners.metamorphic_runner"
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


def run_metamorphic_validator(workspace: Path, spec: dict[str, Any]):
    from swegraph.validators import ValidationResult

    timeout = int(spec.get("timeout", 30))
    env = os.environ.copy()
    pp = [str(workspace), _PROJECT_ROOT]
    if env.get("PYTHONPATH"):
        pp.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pp)
    proc = subprocess.run(
        ["python", "-m", _RUNNER_MODULE],
        input=json.dumps(spec),
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    raw_out = proc.stdout.strip()
    last_line = raw_out.splitlines()[-1] if raw_out else ""
    try:
        data = json.loads(last_line)
    except json.JSONDecodeError:
        return ValidationResult(
            kind="metamorphic",
            passed=False,
            detail=f"runner exit={proc.returncode}; could not parse output",
            raw={"stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]},
        )
    failure = (data.get("failures") or [None])[0]
    return ValidationResult(
        kind="metamorphic",
        passed=bool(data.get("passed")),
        detail=data.get("error") or f"examples={data.get('examples', 0)} relations={spec.get('relations', [])}",
        counterexample=failure,
        raw=data,
    )
