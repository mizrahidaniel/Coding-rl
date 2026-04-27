"""Query-string parsing with type coercion."""

from __future__ import annotations


def _coerce(value: str):
    """Coerce a string to bool / int / float when unambiguous, else return it."""
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in ("null", "none", ""):
        return None
    try:
        if "." in value or "e" in lower:
            return float(value)
        return int(value)
    except ValueError:
        return value


def parse_query(query: str, *, coerce: bool = True) -> dict[str, list]:
    """Parse a ``?key=value&key=value2`` style string.

    Repeated keys collect into a list (preserving order). Empty input yields
    an empty dict. Whitespace around keys / values is stripped.
    """
    out: dict[str, list] = {}
    if not query:
        return out
    if query.startswith("?"):
        query = query[1:]
    for pair in query.split("&"):
        if not pair:
            continue
        if "=" in pair:
            k, _, v = pair.partition("=")
        else:
            k, v = pair, ""
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        out.setdefault(k, []).append(_coerce(v) if coerce else v)
    return out


def flatten_singletons(parsed: dict[str, list]) -> dict[str, object]:
    """Collapse single-element lists in ``parsed`` to their bare value."""
    return {k: (v[0] if len(v) == 1 else v) for k, v in parsed.items()}
