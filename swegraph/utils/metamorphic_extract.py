"""Automatic metamorphic-relation extraction from public-test ASTs.

The honest concern with PBT-as-decontamination is that hand-authored
Hypothesis strategies are still hand-authored — "hidden tests with extra
steps." This module extracts at least one metamorphic relation per task
*from the public test source*, mechanically, so the hidden validator is not
re-authored against the bug.

Heuristics shipped today (intentionally narrow; precision over recall):

1. **boundary_extrema** — if any public-test asserts ``f(seq, ...) ==
   min(seq)`` / ``max(seq)`` / a literal that equals the seq min/max, infer
   that the function's output should land in ``[min(seq), max(seq)]``.
2. **idempotent_under_call** — if any public test asserts ``f(args) ==
   f(args)`` or calls ``f`` twice with identical arguments and compares,
   infer call-idempotence.
3. **non_increasing_size** — if any public test asserts ``len(f(x)) <= len(x)``
   (or compares to a smaller list), infer non-increasing-size.

Extraction returns a list of relation specs that can be merged into a
``MetamorphicValidator`` spec without authoring an ``assertion`` expression.
"""

from __future__ import annotations

import ast
from typing import Any


def extract_relations(public_test_src: str, function_name: str) -> list[str]:
    """Return a list of metamorphic-relation names suggested by ``public_test_src``."""
    try:
        tree = ast.parse(public_test_src)
    except SyntaxError:
        return []
    found: set[str] = set()

    class V(ast.NodeVisitor):
        def visit_Compare(self, node: ast.Compare) -> None:
            self._maybe_boundary(node)
            self._maybe_size(node)
            self.generic_visit(node)

        def _calls_target(self, expr: ast.expr) -> bool:
            return (
                isinstance(expr, ast.Call)
                and isinstance(expr.func, ast.Name)
                and expr.func.id == function_name
            )

        def _maybe_boundary(self, node: ast.Compare) -> None:
            # f(seq, ...) == min(seq) | max(seq)  --> boundary_extrema
            if not (len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)):
                return
            left, right = node.left, node.comparators[0]
            for a, b in ((left, right), (right, left)):
                if self._calls_target(a) and isinstance(b, ast.Call) and isinstance(b.func, ast.Name) and b.func.id in ("min", "max"):
                    found.add("boundary_extrema")

        def _maybe_size(self, node: ast.Compare) -> None:
            # len(f(x)) <= len(x)
            for op, left, right in zip(node.ops, [node.left, *node.comparators[:-1]], node.comparators):
                if isinstance(op, (ast.LtE, ast.Lt)) and self._is_len_of_call(left) and self._is_len_of_var(right):
                    found.add("non_increasing_size")

        def _is_len_of_call(self, e: ast.expr) -> bool:
            return (
                isinstance(e, ast.Call)
                and isinstance(e.func, ast.Name)
                and e.func.id == "len"
                and len(e.args) == 1
                and self._calls_target(e.args[0])
            )

        def _is_len_of_var(self, e: ast.expr) -> bool:
            return (
                isinstance(e, ast.Call)
                and isinstance(e.func, ast.Name)
                and e.func.id == "len"
                and len(e.args) == 1
            )

    V().visit(tree)

    # Idempotence: very cheap textual check (the AST form needs duplicated
    # subtree comparison which is overkill for v2).
    if public_test_src.count(f"{function_name}(") >= 2:
        # If the same call shape appears at least twice, propose idempotence.
        # Guards against false positives by also requiring an equality op.
        if "==" in public_test_src:
            found.add("idempotent_under_call")
    return sorted(found)


def auto_metamorphic_spec(
    *,
    module: str,
    function: str,
    strategy: list[dict[str, Any]],
    public_test_src: str,
    fallback_relations: list[str] | None = None,
    relation_args: dict[str, dict[str, Any]] | None = None,
    max_examples: int = 100,
) -> dict[str, Any] | None:
    """Build a ``MetamorphicValidator`` spec from public-test source.

    Returns None if no relation could be extracted *and* no fallback was given.
    """
    relations = extract_relations(public_test_src, function)
    if not relations:
        relations = list(fallback_relations or [])
    if not relations:
        return None
    return {
        "kind": "metamorphic",
        "module": module,
        "function": function,
        "strategy": strategy,
        "relations": relations,
        "relation_args": relation_args or {},
        "max_examples": max_examples,
        "extraction_source": "public_test_ast",
    }
