"""Hidden validators.

A HiddenValidator is the (kept-off-disk) checker that decides whether the
agent's final state satisfies the task specification. v1 used a single
unit-test runner. v2 supports a discriminated union:

- ``unit_tests``  — original behaviour: write tests to a temp dir and run.
- ``property``    — Hypothesis-driven random sampling against a Python
                    expression that must hold across N draws.
- ``metamorphic`` — auto-extracted invariants (monotonicity, idempotence,
                    boundary respect, round-trip) inferred from public-test
                    AST.

Multi-validator support (TaskSpec.hidden_validators is a list) means a task
can accept *any* patch that satisfies the property under sampling, not just
the one canonical patch. This addresses the v1 "single oracle" complaint.

The dispatch table is exposed as ``HIDDEN_VALIDATORS``; adding a new validator
is a single registry entry, no edits to the runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from pathlib import Path

from swegraph.validators.unit_test import run_unit_tests_validator
from swegraph.validators.property import run_property_validator
from swegraph.validators.metamorphic import run_metamorphic_validator


@dataclass
class ValidationResult:
    kind: str
    passed: bool
    detail: str = ""
    counterexample: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


HIDDEN_VALIDATORS: dict[str, Callable[[Path, dict], ValidationResult]] = {
    "unit_tests": run_unit_tests_validator,
    "property": run_property_validator,
    "metamorphic": run_metamorphic_validator,
}


def run_validators(workspace: Path, validators: list[dict]) -> list[ValidationResult]:
    """Run a list of validator specs against ``workspace``.

    Each spec is a dict with a ``kind`` key matching ``HIDDEN_VALIDATORS``.
    """
    out: list[ValidationResult] = []
    for spec in validators:
        kind = spec.get("kind", "unit_tests")
        fn = HIDDEN_VALIDATORS.get(kind)
        if fn is None:
            out.append(ValidationResult(kind=kind, passed=False, detail=f"unknown validator kind {kind!r}"))
            continue
        out.append(fn(workspace, spec))
    return out


def all_passed(results: list[ValidationResult]) -> bool:
    return bool(results) and all(r.passed for r in results)


def coerce_legacy_hidden_tests(spec_dict: dict[str, Any]) -> list[dict]:
    """v1 stored ``hidden_tests: dict[str, str]`` (filename -> body).

    v2 expects ``hidden_validators: list[dict]``. This shim makes legacy
    JSON tasks continue to load.
    """
    if spec_dict.get("hidden_validators"):
        return spec_dict["hidden_validators"]
    legacy = spec_dict.get("hidden_tests") or {}
    if not legacy:
        return []
    return [{"kind": "unit_tests", "files": legacy}]
