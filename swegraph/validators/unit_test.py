"""Unit-test hidden validator.

Wraps the v1 ``run_hidden_tests`` flow: write the hidden test files to a
temp directory and run pytest against them with ``PYTHONPATH=workspace``.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from swegraph.validators import ValidationResult


_COUNT_RE = re.compile(r"(\d+) (passed|failed|errors|error)\b")


def _parse(text: str) -> tuple[int, int]:
    passed = failed = 0
    for m in _COUNT_RE.finditer(text):
        n, kind = int(m.group(1)), m.group(2)
        if kind == "passed":
            passed = n
        elif kind in ("failed", "errors", "error"):
            failed += n
    return passed, failed


def run_unit_tests_validator(workspace: Path, spec: dict[str, Any]):
    from swegraph.validators import ValidationResult

    files: dict[str, str] = spec.get("files", {})
    timeout: int = int(spec.get("timeout", 30))
    if not files:
        return ValidationResult(kind="unit_tests", passed=True, detail="no hidden tests configured")
    with tempfile.TemporaryDirectory(prefix="swegraph_hidden_") as tmp:
        tdir = Path(tmp)
        paths: list[str] = []
        for rel, body in files.items():
            p = tdir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            paths.append(str(p))
        env = os.environ.copy()
        env["PYTHONPATH"] = str(workspace)
        proc = subprocess.run(
            ["python", "-m", "pytest", "-q", *paths],
            cwd=workspace,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        text = proc.stdout + "\n" + proc.stderr
        passed, failed = _parse(text)
        return ValidationResult(
            kind="unit_tests",
            passed=proc.returncode == 0 and failed == 0,
            detail=f"passed={passed} failed={failed}",
            raw={
                "exit_code": proc.returncode,
                "passed": passed,
                "failed": failed,
                "output": text[-3000:],
            },
        )
