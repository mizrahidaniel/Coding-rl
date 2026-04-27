"""Header normalisation and content-type parsing."""

from __future__ import annotations


def normalise_header(name: str) -> str:
    """Normalise a header name to ``Title-Case-Form``.

    Examples:
        >>> normalise_header("content-type") == "Content-Type"
        >>> normalise_header("X-API-KEY") == "X-Api-Key"
    """
    if not name:
        return ""
    parts = name.replace("_", "-").split("-")
    return "-".join(p.capitalize() for p in parts if p != "")


def parse_content_type(value: str) -> dict[str, str]:
    """Parse a content-type string into ``{type, subtype, parameters...}``.

    ``parse_content_type("application/json; charset=utf-8")`` returns::

        {"type": "application", "subtype": "json", "charset": "utf-8"}
    """
    if not value:
        return {}
    primary, _, params = value.partition(";")
    primary = primary.strip()
    if "/" not in primary:
        out: dict[str, str] = {"type": primary, "subtype": ""}
    else:
        t, _, st = primary.partition("/")
        out = {"type": t.strip(), "subtype": st.strip()}
    for chunk in params.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        k, _, v = chunk.partition("=")
        out[k.strip().lower()] = v.strip().strip('"')
    return out


def header_score(headers: dict[str, str]) -> int:
    """Score a header set by how many normalised core headers are present.

    Used by the routing layer to prioritise complete requests.
    """
    core = {"Content-Type", "Accept", "Authorization"}
    have = {normalise_header(k) for k in headers}
    return len(core & have)
