from __future__ import annotations

from pathlib import Path
import difflib


def unified_diff(before: str, after: str, filename: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )


def compute_patch_size(diff_text: str) -> dict[str, int]:
    added = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deleted = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))
    files = len([ln for ln in diff_text.splitlines() if ln.startswith("diff --git")])
    return {"lines_added": added, "lines_deleted": deleted, "files_changed": files}


def changed_files_from_workspace(workspace: Path, baseline: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for path in workspace.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".pytest_cache" in path.parts:
            continue
        rel = str(path.relative_to(workspace))
        text = path.read_text(encoding="utf-8", errors="ignore")
        if baseline.get(rel) != text:
            changed.append(rel)
    for rel in baseline:
        if rel.startswith(".pytest_cache/"):
            continue
        if not (workspace / rel).exists():
            changed.append(rel)
    return sorted(set(changed))
