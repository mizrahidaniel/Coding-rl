"""Subprocess entrypoint for ``MetamorphicValidator``.

Same shape as ``property_runner`` but with a relation library instead of a
free-form Python ``assertion`` expression.
"""

from __future__ import annotations

import json
import sys
import traceback
from importlib import import_module

from hypothesis import HealthCheck, given, settings

from swegraph.validators._runners._strategy import build_strategy, make_fixed_arity


def _check_relation(name: str, args: list, fn, relation_args: dict):
    if name == "idempotent_under_call":
        a = fn(*args)
        b = fn(*args)
        return a == b, {"a": repr(a), "b": repr(b)}

    if name == "boundary_extrema":
        idx = relation_args.get("arg_index", 0)
        seq = args[idx]
        try:
            lo, hi = min(seq), max(seq)
        except (TypeError, ValueError):
            return True, {"skipped": "non-orderable"}
        result = fn(*args)
        if result is None:
            return True, {"skipped": "none-result"}
        try:
            ok = lo <= result <= hi
        except TypeError:
            return True, {"skipped": "incomparable"}
        return ok, {"lo": lo, "hi": hi, "result": result}

    if name == "monotonic_in_arg":
        idx = relation_args.get("arg_index", 1)
        v = args[idx]
        try:
            v_low = max(int(v) - 1, relation_args.get("min", 0))
            v_high = min(int(v) + 1, relation_args.get("max", v_low + 2))
        except Exception:
            return True, {"skipped": "non-int-arg"}
        tweaked = list(args)
        tweaked[idx] = v_low
        r_low = fn(*tweaked)
        tweaked[idx] = v_high
        r_high = fn(*tweaked)
        if r_low is None or r_high is None:
            return True, {"skipped": "none-result"}
        try:
            ok = r_low <= r_high
        except TypeError:
            return True, {"skipped": "incomparable"}
        return ok, {"low": r_low, "high": r_high}

    if name == "non_increasing_size":
        seq = args[0]
        r = fn(*args)
        try:
            ok = len(r) <= len(seq)
        except TypeError:
            return True, {"skipped": "non-sized"}
        return ok, {"in_size": len(seq), "out_size": len(r)}

    return True, {"unknown_relation": name}


def main(spec: dict) -> dict:
    mod = import_module(spec["module"])
    fn = getattr(mod, spec["function"])
    strats = [build_strategy(s) for s in spec["strategy"]]
    relations = spec["relations"]
    relation_args = spec.get("relation_args", {})
    max_examples = spec.get("max_examples", 100)

    failures: list = []
    examples = {"count": 0}

    def _trampoline(args):
        examples["count"] += 1
        for rel in relations:
            try:
                ok, info = _check_relation(rel, list(args), fn, relation_args.get(rel, {}))
            except Exception as exc:
                failures.append({"relation": rel, "args": [repr(a) for a in args], "exception": repr(exc)})
                raise AssertionError(rel + " raised " + repr(exc))
            if not ok:
                info_safe = {
                    k: (repr(v) if not isinstance(v, (int, float, str, bool, type(None))) else v)
                    for k, v in info.items()
                }
                failures.append({"relation": rel, "args": [repr(a) for a in args], "info": info_safe})
                raise AssertionError(rel + " failed: " + repr(info_safe))

    inner = make_fixed_arity(len(strats))
    inner.__globals__["_trampoline"] = _trampoline
    prop = settings(
        max_examples=max_examples,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )(given(*strats)(inner))

    try:
        prop()
        return {"passed": True, "examples": examples["count"], "failures": []}
    except Exception as exc:
        return {
            "passed": False,
            "examples": examples["count"],
            "failures": failures[:5],
            "error": str(exc)[:1000],
        }


if __name__ == "__main__":
    spec = json.loads(sys.stdin.read())
    try:
        print(json.dumps(main(spec)))
    except Exception:
        print(json.dumps({"passed": False, "error": traceback.format_exc()[:2000]}))
