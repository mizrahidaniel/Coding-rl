"""Tests for the hardened reward-hacking guards (v2)."""

from __future__ import annotations

from pathlib import Path

from swegraph.utils.file_guard import (
    ast_detect_disabled_asserts,
    recursive_conftest_scan,
    reject_symlinks,
    collect_guard_hits,
)


def test_ast_detect_neutralised_assertions():
    src = (
        "def test_x():\n"
        "    assert True  # neutralised\n"
        "def test_y():\n"
        "    if False:\n"
        "        assert 1 == 2\n"
        "    assert True or really_check()\n"
    )
    hits = ast_detect_disabled_asserts(src)
    assert "assert_literal_true" in hits
    assert "if_false_guarding_assert" in hits
    assert "assert_short_circuit_true" in hits


def test_ast_detect_pytest_skip():
    src = (
        "import pytest\n"
        "def test_x():\n"
        "    pytest.skip('not yet')\n"
    )
    hits = ast_detect_disabled_asserts(src)
    assert "pytest_skip_call" in hits


def test_ast_detect_mock_import():
    src = (
        "from unittest.mock import patch\n"
        "def test_x():\n"
        "    with patch('mod.fn'):\n"
        "        assert True\n"
    )
    hits = ast_detect_disabled_asserts(src)
    assert "mock_import_in_test_module" in hits


def test_ast_detect_empty_test_body():
    src = "def test_x():\n    pass\n"
    hits = ast_detect_disabled_asserts(src)
    assert "empty_test_body" in hits


def test_recursive_conftest_scan_finds_subdir(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text("# new\n")
    new = recursive_conftest_scan(tmp_path, baseline_files=set())
    assert "tests/conftest.py" in new


def test_reject_symlinks(tmp_path: Path):
    target = tmp_path / "real.py"
    target.write_text("")
    link = tmp_path / "link.py"
    link.symlink_to(target)
    found = reject_symlinks(tmp_path)
    assert "link.py" in found


def test_collect_guard_hits_pipes_through(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_x():\n    assert True  # gutted\n"
    )
    hits = collect_guard_hits(
        tmp_path,
        public_tests=["tests/test_x.py"],
        changed_files=["tests/test_x.py"],
        baseline_snapshot={"tests/test_x.py": ""},
    )
    rules = {h.rule for h in hits}
    assert "assert_literal_true" in rules
