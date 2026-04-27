"""Deterministic public/hidden test splitter.

Given a list of test files, walk each file's AST and partition individual
test functions (``def test_*``) into "public" and "hidden" sets by hash mod
denominator. Reproducibility: ``(seed, function-qualname)`` produces the
same bucket every time.

Outputs:
- ``public_test_files`` — paths that remain on disk (subset of original
  test functions that mask the hidden split).
- ``hidden_test_files`` — paths whose contents go into the
  ``unit_tests`` validator (off-disk during agent rollouts).

Per the v2 plan's risk callout, splitting *test functions* rather than
*test files* keeps both halves balanced even when a single file has many
tests, and means a single mutated import can't accidentally hide all
hidden tests.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


def _bucket(seed: int, qualname: str, hidden_frac: float) -> bool:
    """Return True if this function should land in the *hidden* bucket."""
    h = hashlib.sha256(f"{seed}::{qualname}".encode()).digest()
    # use first 4 bytes as a uniform-ish [0, 1) value
    val = int.from_bytes(h[:4], "big") / 0xFFFFFFFF
    return val < hidden_frac


def _split_one_file(path: Path, seed: int, hidden_frac: float) -> tuple[str, str]:
    """Return (public_source, hidden_source) for ``path``.

    Both are valid Python: each file keeps the same module-level imports;
    only the test function bodies move.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    public_lines = src.splitlines(keepends=True)
    hidden_lines = src.splitlines(keepends=True)

    public_keep_ranges: list[tuple[int, int]] = []
    hidden_keep_ranges: list[tuple[int, int]] = []
    module_prelude_end = 0

    # Collect module-level statements; tests move, everything else stays.
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        ):
            module_prelude_end = max(module_prelude_end, node.end_lineno or node.lineno)
            public_keep_ranges.append((node.lineno, node.end_lineno or node.lineno))
            hidden_keep_ranges.append((node.lineno, node.end_lineno or node.lineno))
            continue
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            qualname = f"{path.name}::{node.name}"
            is_hidden = _bucket(seed, qualname, hidden_frac)
            if is_hidden:
                hidden_keep_ranges.append((node.lineno, node.end_lineno or node.lineno))
            else:
                public_keep_ranges.append((node.lineno, node.end_lineno or node.lineno))
            continue
        # Helpers / fixtures / non-test functions appear in both halves.
        public_keep_ranges.append((node.lineno, node.end_lineno or node.lineno))
        hidden_keep_ranges.append((node.lineno, node.end_lineno or node.lineno))

    def _materialise(ranges: list[tuple[int, int]]) -> str:
        if not ranges:
            return ""
        keep: list[str] = []
        last = 0
        for lo, hi in sorted(ranges):
            keep.append("".join(src.splitlines(keepends=True)[lo - 1 : hi]))
        return "".join(keep)

    return _materialise(public_keep_ranges), _materialise(hidden_keep_ranges)


def split_tests(
    workspace: Path,
    test_paths: list[str],
    *,
    seed: int = 7,
    hidden_frac: float = 0.3,
) -> tuple[dict[str, str], dict[str, str]]:
    """Split ``test_paths`` (relative to ``workspace``) into public + hidden
    materialised sources.

    Returns ``(public, hidden)`` where each is ``{rel_path: source}``.

    The hidden bucket reuses the same relative path so the unit-test
    validator can run them as siblings of the public set in its temp dir.
    """
    public: dict[str, str] = {}
    hidden: dict[str, str] = {}
    for rel in test_paths:
        p = workspace / rel
        if not p.exists() or not p.suffix == ".py":
            continue
        pub_src, hid_src = _split_one_file(p, seed, hidden_frac)
        if pub_src.strip():
            public[rel] = pub_src
        if hid_src.strip():
            hidden[rel] = hid_src
    return public, hidden
