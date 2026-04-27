"""AST-based procedural mutation operators.

Each operator inspects a source file and yields a list of candidate
``Mutation`` instances. A mutation is a single text replacement at a known
``(line, col)`` position. Mutations are intentionally small (one operator
per AST node) so the resulting diffs are < 5 lines and the hidden bug is
local and explainable.

Operators shipped:
- ``OffByOneOperator`` — adjusts integer literals 0/1 by ±1, slice
  endpoints, range bounds.
- ``CompareSwapOperator`` — flips ``<``/``<=``, ``>``/``>=``, ``==``/``!=``.
- ``BooleanFlipOperator`` — flips ``True``/``False`` constants and ``and``/``or``.
- ``ReturnValueOperator`` — replaces a returned literal with a near-neighbour
  (``""`` -> ``" "``, ``[]`` -> ``[None]``, ``{}`` -> ``{"_": None}``,
  ``None`` -> ``False``, integer literals shifted).
- ``BinaryOpOperator`` — swaps ``+``/``-``, ``*``/``/`` (where AST allows).

These are the same families mutmut implements (with looser names). The
implementation here is deliberately simpler so we own the survival pipeline
end-to-end; ``mutmut`` adds a process-level cache and a richer registry but
also a heavier dependency.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Mutation:
    """A single procedural mutation against a source file."""

    operator: str
    path: str
    line: int
    col: int
    before: str
    after: str
    description: str = ""

    @property
    def mutation_id(self) -> str:
        return f"{self.path}:{self.line}:{self.col}:{self.operator}:{self.before}:{self.after}"


def _replace_at_segment(src: str, line: int, col: int, before: str, after: str) -> str | None:
    """Replace the first occurrence of ``before`` at the given (1-indexed)
    line/col with ``after``. Returns the new source, or ``None`` if the
    segment didn't match (e.g. the AST col disagrees with the textual col).
    """
    lines = src.splitlines(keepends=True)
    idx = line - 1
    if idx < 0 or idx >= len(lines):
        return None
    cur = lines[idx]
    if cur[col : col + len(before)] != before:
        # Try to find ``before`` later on the line; AST col can lag.
        pos = cur.find(before, col)
        if pos == -1:
            return None
        col = pos
    new = cur[:col] + after + cur[col + len(before) :]
    if new == cur:
        return None
    lines[idx] = new
    return "".join(lines)


def replace_at_line_col(
    file_path: Path,
    line: int,
    col: int,
    before: str,
    after: str,
) -> bool:
    """Public wrapper: precise (line, col) text replacement on disk.

    Returns ``True`` when the replacement was applied.
    """
    if not file_path.exists():
        return False
    src = file_path.read_text(encoding="utf-8")
    new = _replace_at_segment(src, line, col, before, after)
    if new is None:
        return False
    file_path.write_text(new, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------


def _off_by_one_mutations(tree: ast.AST, src: str, path: str) -> list[Mutation]:
    out: list[Mutation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and -2 <= node.value <= 2:
            for delta in (-1, 1):
                new_val = node.value + delta
                before = repr(node.value)
                after = repr(new_val)
                if _replace_at_segment(src, node.lineno, node.col_offset, before, after) is None:
                    continue
                out.append(
                    Mutation(
                        operator="off_by_one",
                        path=path,
                        line=node.lineno,
                        col=node.col_offset,
                        before=before,
                        after=after,
                        description=f"int constant {before} -> {after}",
                    )
                )
    return out


def _compare_swap_mutations(tree: ast.AST, src: str, path: str) -> list[Mutation]:
    swaps = {
        ast.Lt: ("<", "<="),
        ast.LtE: ("<=", "<"),
        ast.Gt: (">", ">="),
        ast.GtE: (">=", ">"),
        ast.Eq: ("==", "!="),
        ast.NotEq: ("!=", "=="),
    }
    out: list[Mutation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for op_node, op in zip(node.ops, node.ops):
            pair = swaps.get(type(op))
            if pair is None:
                continue
            before, after = pair
            # Try to locate the operator on the line at or after Compare's col
            # (Python AST does not track per-op positions). Use the first
            # match on the line.
            line = node.lineno
            col = node.col_offset
            res = _replace_at_segment(src, line, col, before, after)
            if res is None:
                continue
            out.append(
                Mutation(
                    operator="compare_swap",
                    path=path,
                    line=line,
                    col=col,
                    before=before,
                    after=after,
                    description=f"comparison {before} -> {after}",
                )
            )
    return out


def _boolean_flip_mutations(tree: ast.AST, src: str, path: str) -> list[Mutation]:
    flips = {
        True: ("True", "False"),
        False: ("False", "True"),
    }
    boolop_flips = {
        ast.And: ("and", "or"),
        ast.Or: ("or", "and"),
    }
    out: list[Mutation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            before, after = flips[node.value]
            if _replace_at_segment(src, node.lineno, node.col_offset, before, after) is None:
                continue
            out.append(
                Mutation(
                    operator="boolean_flip",
                    path=path,
                    line=node.lineno,
                    col=node.col_offset,
                    before=before,
                    after=after,
                    description=f"boolean literal {before} -> {after}",
                )
            )
        elif isinstance(node, ast.BoolOp):
            pair = boolop_flips.get(type(node.op))
            if pair is None:
                continue
            before, after = pair
            if _replace_at_segment(src, node.lineno, node.col_offset, before, after) is None:
                continue
            out.append(
                Mutation(
                    operator="boolean_flip",
                    path=path,
                    line=node.lineno,
                    col=node.col_offset,
                    before=before,
                    after=after,
                    description=f"boolop {before} -> {after}",
                )
            )
    return out


def _return_value_mutations(tree: ast.AST, src: str, path: str) -> list[Mutation]:
    """Mutate the literal in a ``return <literal>`` statement."""
    out: list[Mutation] = []
    swaps = [
        ("True", "False"),
        ("False", "True"),
        ("None", "False"),
        ("[]", "[None]"),
        ("{}", "{'_': None}"),
        ('""', '" "'),
        ("''", '" "'),
    ]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return):
            continue
        if node.value is None:
            continue
        try:
            literal = ast.unparse(node.value)
        except Exception:
            continue
        for before, after in swaps:
            if literal == before:
                if _replace_at_segment(src, node.lineno, node.col_offset, before, after) is None:
                    continue
                out.append(
                    Mutation(
                        operator="return_value",
                        path=path,
                        line=node.lineno,
                        col=node.col_offset,
                        before=before,
                        after=after,
                        description=f"return literal {before} -> {after}",
                    )
                )
    return out


def _binary_op_mutations(tree: ast.AST, src: str, path: str) -> list[Mutation]:
    swaps = {
        ast.Add: ("+", "-"),
        ast.Sub: ("-", "+"),
        ast.Mult: ("*", "/"),
        ast.Div: ("/", "*"),
        ast.FloorDiv: ("//", "/"),
    }
    out: list[Mutation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp):
            continue
        pair = swaps.get(type(node.op))
        if pair is None:
            continue
        before, after = pair
        # AST gives node.lineno/col for the LEFT operand; the operator sits
        # somewhere after. Search forward on the line (and a fallback line).
        line = node.lineno
        col = node.col_offset
        if _replace_at_segment(src, line, col, before, after) is None:
            continue
        out.append(
            Mutation(
                operator="binary_op",
                path=path,
                line=line,
                col=col,
                before=before,
                after=after,
                description=f"binop {before} -> {after}",
            )
        )
    return out


MUTATION_OPERATORS = {
    "off_by_one": _off_by_one_mutations,
    "compare_swap": _compare_swap_mutations,
    "boolean_flip": _boolean_flip_mutations,
    "return_value": _return_value_mutations,
    "binary_op": _binary_op_mutations,
}


def enumerate_mutations(
    source_path: Path,
    *,
    operators: list[str] | None = None,
) -> list[Mutation]:
    """Enumerate all candidate mutations in ``source_path``.

    Skips files that fail to parse. Returns an empty list for non-Python
    inputs.
    """
    if source_path.suffix != ".py":
        return []
    src = source_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out: list[Mutation] = []
    rel_path = str(source_path)
    selected = operators or list(MUTATION_OPERATORS.keys())
    for op_name in selected:
        fn = MUTATION_OPERATORS.get(op_name)
        if fn is None:
            continue
        out.extend(fn(tree, src, rel_path))
    # De-duplicate by mutation_id.
    seen: set[str] = set()
    deduped: list[Mutation] = []
    for m in out:
        if m.mutation_id in seen:
            continue
        seen.add(m.mutation_id)
        deduped.append(m)
    return deduped


def apply_mutation(workspace: Path, mutation: Mutation, *, target: Path | None = None) -> bool:
    """Apply ``mutation`` in-place under ``workspace``.

    Returns True on success. ``target`` overrides the path resolution if the
    mutation was enumerated against a different on-disk location.
    """
    file_path = target if target is not None else workspace / Path(mutation.path).name
    if not file_path.exists():
        # Fall back: the mutation path may be absolute or workspace-relative.
        candidate = workspace / mutation.path
        if candidate.exists():
            file_path = candidate
        else:
            return False
    src = file_path.read_text(encoding="utf-8")
    new = _replace_at_segment(src, mutation.line, mutation.col, mutation.before, mutation.after)
    if new is None:
        return False
    file_path.write_text(new, encoding="utf-8")
    return True
