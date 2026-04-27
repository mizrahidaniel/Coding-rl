from __future__ import annotations

import subprocess
import tempfile
import os
from pathlib import Path


def run_pytest(workspace: Path, test_paths: list[str], timeout: int = 20) -> dict:
    cmd = ["python", "-m", "pytest", "-q", *test_paths]
    proc = subprocess.run(cmd, cwd=workspace, text=True, capture_output=True, timeout=timeout)
    text = proc.stdout + "\n" + proc.stderr
    failed = 0
    passed = 0
    for line in text.splitlines():
        if " failed" in line or " failed," in line:
            parts = line.split()
            for i, tok in enumerate(parts):
                if tok == "failed" and i > 0 and parts[i - 1].isdigit():
                    failed = int(parts[i - 1])
                if tok == "passed" and i > 0 and parts[i - 1].isdigit():
                    passed = int(parts[i - 1])
        if line.strip().endswith("passed") and line.strip().split()[0].isdigit():
            passed = int(line.strip().split()[0])
    return {
        "exit_code": proc.returncode,
        "passed": passed,
        "failed": failed,
        "output": text[-3000:],
        "all_passed": proc.returncode == 0,
    }


def run_hidden_tests(workspace: Path, hidden_tests: dict[str, str], timeout: int = 20) -> dict:
    with tempfile.TemporaryDirectory(prefix="swegraph_hidden_") as tmp:
        tdir = Path(tmp)
        test_paths: list[str] = []
        for rel, content in hidden_tests.items():
            p = tdir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            test_paths.append(str(p))
        cmd = ["python", "-m", "pytest", "-q", *test_paths]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(workspace)
        proc = subprocess.run(cmd, cwd=workspace, text=True, capture_output=True, timeout=timeout, env=env)
        return {"exit_code": proc.returncode, "output": (proc.stdout + "\n" + proc.stderr)[-3000:], "all_passed": proc.returncode == 0}
