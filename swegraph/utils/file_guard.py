from __future__ import annotations

from pathlib import Path


SUSPICIOUS_PYTEST_FILES = {"pytest.ini", "pyproject.toml", "conftest.py"}


def tests_deleted(workspace: Path, expected_tests: list[str]) -> bool:
    return any(not (workspace / t).exists() for t in expected_tests)


def suspicious_pytest_changes(changed_files: list[str]) -> bool:
    return any(Path(f).name in SUSPICIOUS_PYTEST_FILES for f in changed_files)
