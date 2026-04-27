from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path


# Tail-summary pytest counts: "1 passed, 2 failed in 0.10s" etc.
_COUNT_RE = re.compile(r"(\d+) (passed|failed|errors|error)\b")
# Per-test status with -rN -v: lines like "PASSED tests/foo.py::test_bar"
# or "FAILED tests/foo.py::test_bar - AssertionError".
_PER_TEST_RE = re.compile(
    r"^(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(?P<nodeid>\S+)",
    re.MULTILINE,
)


def _parse_pytest_counts(text: str) -> tuple[int, int]:
    passed = failed = 0
    for m in _COUNT_RE.finditer(text):
        n, kind = int(m.group(1)), m.group(2)
        if kind == "passed":
            passed = n
        elif kind in ("failed", "errors", "error"):
            failed += n
    return passed, failed


def _parse_per_test_status(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _PER_TEST_RE.finditer(text):
        out[m.group("nodeid")] = m.group("status").lower()
    return out


def run_pytest(workspace: Path, test_paths: list[str], timeout: int = 30) -> dict:
    """Run pytest with verbose + per-test reporting so we can populate
    ``TrajectoryStep.per_test_status`` without a second pass."""
    cmd = ["python", "-m", "pytest", "-q", "-rN", *test_paths]
    proc = subprocess.run(cmd, cwd=workspace, text=True, capture_output=True, timeout=timeout)
    text = proc.stdout + "\n" + proc.stderr
    passed, failed = _parse_pytest_counts(text)
    return {
        "exit_code": proc.returncode,
        "passed": passed,
        "failed": failed,
        "output": text[-3000:],
        "full_stdout": proc.stdout,
        "full_stderr": proc.stderr,
        "per_test_status": _parse_per_test_status(text),
        "all_passed": proc.returncode == 0 and failed == 0,
    }


def run_hidden_tests(workspace: Path, hidden_tests: dict[str, str], timeout: int = 30) -> dict:
    """Legacy back-compat: matches v1 ``run_hidden_tests`` signature.

    v2 callers should prefer ``swegraph.validators.run_validators`` directly.
    """
    if not hidden_tests:
        return {"exit_code": 0, "output": "", "all_passed": True}
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
