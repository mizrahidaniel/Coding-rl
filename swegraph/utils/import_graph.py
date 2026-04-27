"""Static import-graph utility for causal-hop task generation and reward.

Computes the shortest path (in module-import edges) between two modules in
a workspace by AST-parsing every ``.py`` file and building a directed graph
of ``from X import ...`` and ``import X.Y`` references. ``hop_count`` is the
number of edges on the shortest directed path.

This is intentionally static (no runtime hooks) — for v2 the import edges
the agent has to traverse to find the root cause are the difficulty axis,
and a static graph is the cheapest controllable proxy.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path


def _module_name_for(path: Path, workspace: Path) -> str:
    rel = path.relative_to(workspace)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)


def build_import_graph(workspace: Path) -> dict[str, set[str]]:
    """Return ``{module_name -> set(imported_module_names)}``.

    Skips ``tests/`` and dotfiles. Best-effort: syntax errors yield no edges
    for that file but do not abort the build.
    """
    graph: dict[str, set[str]] = {}
    files: list[Path] = []
    for p in workspace.rglob("*.py"):
        rel = p.relative_to(workspace)
        if any(part.startswith(".") or part == "tests" or part == "__pycache__" for part in rel.parts):
            continue
        files.append(p)

    known: set[str] = {_module_name_for(p, workspace) for p in files}

    for p in files:
        mod = _module_name_for(p, workspace)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            graph.setdefault(mod, set())
            continue
        edges = graph.setdefault(mod, set())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                target = node.module
                edges.add(target)
                # also record the leaf re-exports (from X import Y -> X.Y)
                for alias in node.names:
                    if alias.name != "*":
                        edges.add(f"{target}.{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    edges.add(alias.name)
        # restrict to nodes the workspace actually defines so external deps
        # don't dominate the graph
        graph[mod] = {e for e in edges if any(e == k or e.startswith(k + ".") for k in known)}
    return graph


def hop_count(graph: dict[str, set[str]], src: str, dst: str) -> int | None:
    """Shortest directed-edge distance from ``src`` to ``dst``.

    Returns ``None`` if no path exists. ``src == dst`` returns 0.
    """
    if src == dst:
        return 0
    if src not in graph:
        return None
    visited: set[str] = {src}
    q: deque[tuple[str, int]] = deque([(src, 0)])
    while q:
        node, d = q.popleft()
        for nb in graph.get(node, set()):
            if nb == dst or nb.startswith(dst + "."):
                return d + 1
            if nb in visited:
                continue
            visited.add(nb)
            q.append((nb, d + 1))
    return None
