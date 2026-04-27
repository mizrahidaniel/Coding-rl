"""Subprocess entrypoint for ``PropertyValidator``.

Reads a JSON spec from stdin, runs the Hypothesis property in this
subprocess (with ``PYTHONPATH`` pointing at the agent's workspace), prints
a single JSON line summarising the result.
"""

from __future__ import annotations

import json
import sys
import traceback
from importlib import import_module

from hypothesis import HealthCheck, given, settings

from swegraph.validators._runners._strategy import build_strategy, make_fixed_arity


def main(spec: dict) -> dict:
    mod = import_module(spec["module"])
    fn = getattr(mod, spec["function"])
    strats = [build_strategy(s) for s in spec["strategy"]]
    assertion_src = spec["assertion"]
    max_examples = spec.get("max_examples", 200)

    hits: list = []
    examples = {"count": 0}

    def _trampoline(args):
        examples["count"] += 1
        try:
            result = fn(*args)
        except Exception as exc:
            hits.append({"args": [repr(a) for a in args], "exception": repr(exc)})
            raise AssertionError("function raised: " + repr(exc))
        ok = eval(
            assertion_src,
            {
                "__builtins__": __builtins__,
                "min": min,
                "max": max,
                "len": len,
                "abs": abs,
                "sum": sum,
                "any": any,
                "all": all,
            },
            {"args": list(args), "result": result},
        )
        if not ok:
            hits.append({"args": [repr(a) for a in args], "result": repr(result)})
            raise AssertionError("property failed for args=" + repr(args) + " result=" + repr(result))

    inner = make_fixed_arity(len(strats))
    inner.__globals__["_trampoline"] = _trampoline
    prop = settings(
        max_examples=max_examples,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )(given(*strats)(inner))

    try:
        prop()
        return {"passed": True, "examples": examples["count"], "hits": []}
    except Exception as exc:
        return {
            "passed": False,
            "examples": examples["count"],
            "hits": hits[:5],
            "error": str(exc)[:1000],
        }


if __name__ == "__main__":
    spec = json.loads(sys.stdin.read())
    try:
        print(json.dumps(main(spec)))
    except Exception:
        print(json.dumps({"passed": False, "error": traceback.format_exc()[:2000]}))
