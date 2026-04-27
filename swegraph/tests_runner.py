from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path


# Match pytest's tail summary forms:
#   "1 passed in 0.00s"
#   "2 failed, 3 passed in 1.20s"
#   "1 passed, 1 warning in 0.10s"
_COUNT_RE = re.compile(r"(\d+) (passed|failed|errors|error)\b")


def _parse_pytest_counts(text: str) -> tuple[int, int]:
    passed = failed = 0
    for m in _COUNT_RE.finditer(text):
        n = int(m.group(1))
        kind = m.group(2)
        if kind == "passed":
            passed = n
        elif kind in ("failed", "errors", "error"):
            failed += n
    return passed, failed


def run_pytest(workspace: Path, test_paths: list[str], timeout: int = 30) -> dict:
    cmd = ["python", "-m", "pytest", "-q", *test_paths]
    proc = subprocess.run(cmd, cwd=workspace, text=True, capture_output=True, timeout=timeout)
    text = proc.stdout + "\n" + proc.stderr
    passed, failed = _parse_pytest_counts(text)
    return {
        "exit_code": proc.returncode,
        "passed": passed,
        "failed": failed,
        "output": text[-3000:],
        "all_passed": proc.returncode == 0 and failed == 0,
    }


def run_hidden_tests(workspace: Path, hidden_tests: dict[str, str], timeout: int = 30) -> dict:
    """Execute hidden tests against the workspace without leaving them on disk.

    Tests are written to a temp directory and run with PYTHONPATH=workspace so
    the agent never has the chance to read or edit them.
    """
    with tempfile.TemporaryDirectory(prefix="swegraph_hidden_") as tmp:
        tdir = Path(tmp)
        test_paths: list[str] = []
        for rel, content in hidden_tests.items():
            p = tdir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            test_paths.append(str(p))
        env = os.environ.copy()
        env["PYTHONPATH"] = str(workspace)
        cmd = ["python", "-m", "pytest", "-q", *test_paths]
        proc = subprocess.run(
            cmd, cwd=workspace, text=True, capture_output=True, timeout=timeout, env=env
        )
        text = proc.stdout + "\n" + proc.stderr
        passed, failed = _parse_pytest_counts(text)
        return {
            "exit_code": proc.returncode,
            "passed": passed,
            "failed": failed,
            "output": text[-3000:],
            "all_passed": proc.returncode == 0 and failed == 0,
        }
