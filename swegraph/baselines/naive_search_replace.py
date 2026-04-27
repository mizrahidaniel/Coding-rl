from __future__ import annotations

import re
from typing import Iterator


# Heuristic textual swaps for common boundary-bug shapes. Intentionally narrow:
# the naive baseline should solve easy off-by-one bugs but fail on config
# renames or new-feature signatures.
HEURISTIC_SWAPS: list[tuple[str, str]] = [
    (
        r"int\(round\(len\(([A-Za-z_]\w*)\) \* \(p / 100\)\)\)",
        r"int(round((len(\1) - 1) * (p / 100)))",
    ),
    (r"if p < 0:", "if p <= 0:"),
    (r"if p > 100:", "if p >= 100:"),
]


def _list_repo_files(api) -> list[str]:
    out = api.run_command(
        "find . -name '*.py' -not -path './.git/*' -not -path '*/__pycache__/*'"
    )
    files: list[str] = []
    for line in out.get("stdout", "").splitlines():
        line = line.strip()
        if line.startswith("./"):
            line = line[2:]
        if line:
            files.append(line)
    return files


def _candidate_modules(test_output: str, repo_files: list[str]) -> list[str]:
    return [
        f
        for f in repo_files
        if f.endswith(".py")
        and not f.startswith("tests/")
        and "/tests/" not in f
        and f in test_output
    ]


def run_naive_search_replace(api, task) -> Iterator:
    """Heuristic search/replace baseline.

    Strategy (intentionally simple, NOT using task.mutation_metadata):
      1. Run public tests to discover failures.
      2. Locate candidate source files from failing tracebacks.
      3. Apply a handful of textual swaps that catch common boundary bugs.
      4. Re-run tests; finish.
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

    repo_files = _list_repo_files(api)
    yield Action(
        "run_command",
        {"command": "find . -name '*.py'", "exit_code": 0, "stdout_summary": ""},
        "enumerate source files",
    )

    candidates = _candidate_modules(pre.get("stdout", "") + pre.get("stderr", ""), repo_files)
    if not candidates:
        guess = f"{task.repo_id}/core.py"
        if guess in repo_files:
            candidates = [guess]

    edited_any = False
    for path in candidates:
        try:
            content = api.read_file(path)
        except FileNotFoundError:
            continue
        yield Action("read_file", {"path": path, "size": len(content)}, "inspect candidate source")

        new_content = content
        for pattern, repl in HEURISTIC_SWAPS:
            new_content = re.sub(pattern, repl, new_content)
        if new_content != content:
            api.write_file(path, new_content)
            edited_any = True
            yield Action(
                "write_file",
                {"path": path, "bytes": len(new_content)},
                "apply heuristic boundary-bug swap",
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
        "verify after edits" if edited_any else "no heuristic matched; verify unchanged",
    )
    api.finish()
    yield Action("finish", {}, "submit")
