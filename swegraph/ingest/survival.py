"""Mutation survival classifier.

Given a workspace + a candidate mutation + a test command, this module:

1. Copies the workspace into a scratch directory.
2. Runs the test command on the *unmutated* copy. If that fails we abort —
   the test suite isn't green to begin with and survival is undefined.
3. Applies the mutation in the scratch copy.
4. Re-runs the test command.
5. Classifies the outcome:
   - ``killed``   — exit code != 0 (the suite caught the mutation).
   - ``survived`` — exit code == 0 (the suite did NOT catch it; this is
                    a valid SWEGraph task seed).
   - ``broke_syntax`` — Python failed to parse / import the mutated file.
   - ``timeout`` — the test command exceeded ``timeout`` seconds.
   - ``baseline_red`` — the unmutated suite already failed.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from swegraph.ingest.mutators import Mutation, apply_mutation


@dataclass
class SurvivalResult:
    mutation: Mutation
    classification: str  # killed | survived | broke_syntax | timeout | baseline_red
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_s: float = 0.0


def _run(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)


def classify_mutation(
    workspace: Path,
    mutation: Mutation,
    *,
    test_command: list[str] | None = None,
    timeout: int = 30,
) -> SurvivalResult:
    """Apply ``mutation`` to a scratch copy of ``workspace`` and run tests."""
    cmd = test_command or ["python", "-m", "pytest", "-q", "tests"]
    import time

    with tempfile.TemporaryDirectory(prefix="swegraph_survival_") as tmp:
        scratch = Path(tmp) / "ws"
        shutil.copytree(workspace, scratch)
        # 1. Verify baseline green
        try:
            base = _run(cmd, scratch, timeout)
        except subprocess.TimeoutExpired:
            return SurvivalResult(mutation, "baseline_red", None, "", "", 0.0)
        if base.returncode != 0:
            return SurvivalResult(mutation, "baseline_red", base.returncode, base.stdout[-300:], base.stderr[-300:], 0.0)

        # 2. Apply mutation
        target = scratch / mutation.path
        if not target.exists():
            target = scratch / Path(mutation.path).name
        ok = apply_mutation(scratch, mutation, target=target)
        if not ok:
            return SurvivalResult(mutation, "broke_syntax", None, "", "could not apply mutation", 0.0)

        # 3. Run mutated tests
        try:
            t0 = time.monotonic()
            res = _run(cmd, scratch, timeout)
            duration = time.monotonic() - t0
        except subprocess.TimeoutExpired:
            return SurvivalResult(mutation, "timeout", None, "", "", float(timeout))

        if res.returncode == 0:
            return SurvivalResult(mutation, "survived", res.returncode, res.stdout[-300:], res.stderr[-300:], duration)

        # Distinguish syntax/import errors from real test failures.
        combined = (res.stdout or "") + (res.stderr or "")
        if "SyntaxError" in combined or "ImportError" in combined and "ModuleNotFoundError" not in combined:
            return SurvivalResult(mutation, "broke_syntax", res.returncode, res.stdout[-300:], res.stderr[-300:], duration)

        return SurvivalResult(mutation, "killed", res.returncode, res.stdout[-300:], res.stderr[-300:], duration)
