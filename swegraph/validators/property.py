"""Property-based hidden validator (Hypothesis).

Spec format::

    {
      "kind": "property",
      "module": "stats_utils.core",
      "function": "percentile",
      "strategy": [...],                    # one entry per positional arg
      "assertion": "result is None or (min(args[0]) <= result <= max(args[0]))",
      "max_examples": 200,
      "timeout": 30
    }

The assertion is evaluated in a tightly-scoped namespace with ``args`` (the
sampled positional arguments) and ``result`` (the function's return value)
bound. Property success = all draws satisfy the assertion.

The actual Hypothesis loop runs in a subprocess (see
``swegraph/validators/_runners/property_runner.py``) with
``PYTHONPATH=workspace`` so the workspace's code is exercised in isolation.
Keeping the runner in a real ``.py`` file (instead of an embedded source
string) avoids triple-quoted-string escape pitfalls.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


_RUNNER_MODULE = "swegraph.validators._runners.property_runner"
# Project root that ships ``swegraph.validators._runners.*``; we put the
# *workspace* first on PYTHONPATH so the agent's code wins on imports, then
# this root so the runner module is locatable.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


def run_property_validator(workspace: Path, spec: dict[str, Any]):
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
            kind="property",
            passed=False,
            detail=f"runner exit={proc.returncode}; could not parse output",
            raw={"stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]},
        )
    counterexample = (data.get("hits") or [None])[0]
    return ValidationResult(
        kind="property",
        passed=bool(data.get("passed")),
        detail=data.get("error") or f"examples={data.get('examples', 0)}",
        counterexample=counterexample,
        raw=data,
    )
