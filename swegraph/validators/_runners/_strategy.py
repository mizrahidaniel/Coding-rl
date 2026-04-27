"""Shared Hypothesis strategy builder used by property + metamorphic runners."""

from __future__ import annotations

from hypothesis import strategies as st


def build_strategy(spec: dict):
    kind = spec["kind"]
    if kind == "integers":
        return st.integers(min_value=spec.get("min_value"), max_value=spec.get("max_value"))
    if kind == "floats":
        return st.floats(
            min_value=spec.get("min_value"),
            max_value=spec.get("max_value"),
            allow_nan=spec.get("allow_nan", False),
            allow_infinity=spec.get("allow_infinity", False),
        )
    if kind == "text":
        return st.text(min_size=spec.get("min_size", 0), max_size=spec.get("max_size", 50))
    if kind == "booleans":
        return st.booleans()
    if kind == "lists":
        inner_kind = spec.get("of", "integers")
        inner_spec: dict = {"kind": inner_kind}
        for k in ("min_value", "max_value"):
            if k in spec:
                inner_spec[k] = spec[k]
        return st.lists(
            build_strategy(inner_spec),
            min_size=spec.get("min_size", 0),
            max_size=spec.get("max_size", 50),
        )
    if kind == "tuples":
        return st.tuples(*[build_strategy(s) for s in spec["fields"]])
    if kind == "sampled_from":
        return st.sampled_from(spec["values"])
    raise ValueError("unknown strategy kind " + kind)


def make_fixed_arity(n: int):
    """Hypothesis disallows ``*args`` on @given-decorated functions, so we
    synthesize a fixed-arity wrapper around a single trampoline callback."""
    sig = ", ".join(f"a{i}" for i in range(n))
    src = f"def _prop({sig}):\n    return _trampoline([{sig}])\n"
    ns: dict = {}
    exec(src, ns)
    return ns["_prop"]
