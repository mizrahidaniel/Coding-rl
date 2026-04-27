"""Causal-hop task family.

Each task plants a single mutation in a leaf module of an import chain
``a -> b -> c`` and exposes a public test that imports only the top of the
chain. The fault must therefore be localised through ``hops`` import edges
to be diagnosed and fixed. ``mutation_metadata.import_hops`` is recorded so
the reward engine and downstream analyses can stratify by graph distance.

This is the genuinely-novel axis the v2 plan committed to: prior art measures
"frontier difficulty" empirically (solver pass rate, e.g. Self-Play SWE-RL)
or by file count (SWE-bench Pro). Nobody publicly uses the static
import-graph distance as a generator-side knob.
"""

from __future__ import annotations

import random

from swegraph.schema import TaskSpec
from swegraph.utils.metamorphic_extract import auto_metamorphic_spec


# Each entry mutates a single leaf-module function. ``hops`` is the shortest
# import-edge distance from the mutated module to the module the public test
# imports.
_MUTATIONS = [
    {
        "name": "clamp_swap_bounds",
        "path": "multi_pkg/c.py",
        "old": "    if value < lo:\n        return lo\n    if value > hi:\n        return hi\n    return value",
        "new": "    if value < lo:\n        return hi\n    if value > hi:\n        return lo\n    return value",
        "hops": 2,
        "root_cause_file": "multi_pkg/c.py",
        "function": "process_batch",
        "module": "multi_pkg.a",
        "fallback_relations": ["boundary_extrema"],
        "relation_args": {"boundary_extrema": {"arg_index": 0}},
    },
    {
        "name": "safe_divide_drops_zero_guard",
        "path": "multi_pkg/c.py",
        "old": "    if denominator == 0:\n        return 0.0\n    return numerator / denominator",
        "new": "    return numerator / denominator if denominator else float('inf')",
        "hops": 2,
        "root_cause_file": "multi_pkg/c.py",
        "function": "process_batch",
        "module": "multi_pkg.a",
        "fallback_relations": ["boundary_extrema"],
        "relation_args": {"boundary_extrema": {"arg_index": 0}},
    },
    {
        "name": "normalise_inverts_axis",
        "path": "multi_pkg/b.py",
        "old": "    return safe_divide(clamped - lo, hi - lo)",
        "new": "    return safe_divide(hi - clamped, hi - lo)",
        "hops": 1,
        "root_cause_file": "multi_pkg/b.py",
        "function": "process_batch",
        "module": "multi_pkg.a",
        "fallback_relations": ["boundary_extrema"],
        "relation_args": {"boundary_extrema": {"arg_index": 0}},
    },
]


_USER_PROMPTS = [
    "process_batch is producing weird outputs lately — could you take a look?",
    "Hey, the batch processing seems to flip results sometimes. Mind investigating?",
    "Reports came in that process_batch returns values outside [0, 1]. Please fix.",
    "Something is off with how multi_pkg processes batches. Please patch it without changing the public API.",
]


_PUBLIC_TEST_SRC = '''from multi_pkg.a import process_batch


def test_process_batch_within_bounds():
    out = process_batch([0, 5, 10], 0, 10)
    assert out == [0.0, 0.5, 1.0]


def test_process_batch_clamps_out_of_range():
    out = process_batch([-5, 15], 0, 10)
    assert all(0.0 <= v <= 1.0 for v in out)
'''


def _make_validator_spec(mut: dict) -> dict:
    """Build the metamorphic validator spec, attempting auto-extraction first.

    Falls back to the mutation's declared relations if the AST extractor finds
    nothing in the public-test source. We log ``extraction_source`` either
    way so reviewers can audit.
    """
    strategy = [
        {"kind": "lists", "of": "integers", "min_value": -1000, "max_value": 1000, "min_size": 1, "max_size": 30},
        {"kind": "integers", "min_value": -100, "max_value": 0},
        {"kind": "integers", "min_value": 1, "max_value": 100},
    ]
    spec = auto_metamorphic_spec(
        module=mut["module"],
        function=mut["function"],
        strategy=strategy,
        public_test_src=_PUBLIC_TEST_SRC,
        fallback_relations=mut["fallback_relations"],
        relation_args=mut.get("relation_args"),
        max_examples=80,
    )
    # Tighten the strategy: hi must be > lo for normalise to be defined.
    if spec is not None:
        spec["strategy"][1] = {"kind": "integers", "min_value": -50, "max_value": -1}
        spec["strategy"][2] = {"kind": "integers", "min_value": 1, "max_value": 50}
    return spec  # may still be None if extractor and fallback both fail


def generate_causal_hop_task(
    task_id: str, seed: int, reward_config: dict[str, float]
) -> TaskSpec:
    rng = random.Random(seed)
    mut = rng.choice(_MUTATIONS)
    user_prompt = rng.choice(_USER_PROMPTS)

    validator_spec = _make_validator_spec(mut)
    hidden_validators: list[dict] = []
    if validator_spec is not None:
        hidden_validators.append(validator_spec)
    # Hidden unit tests deliberately exercise three failure modes that the
    # public tests + the auto-extracted boundary_extrema property do *not*
    # detect:
    #   1. swap-bounds clamp returns hi instead of lo (and vice versa) on
    #      out-of-range inputs - public test #2 only checks that outputs lie
    #      in [0, 1], which still holds for swapped clamps.
    #   2. dropping the zero-guard in safe_divide turns lo == hi from
    #      "every output is 0.0" into a ZeroDivisionError or inf.
    #   3. inverting the normalise axis is already caught by the public
    #      test (anchor here for completeness).
    hidden_validators.append({
        "kind": "unit_tests",
        "files": {
            "tests/test_hidden_causal_hop.py": (
                "from multi_pkg.a import process_batch\n\n\n"
                "def test_process_batch_negative_range():\n"
                "    assert process_batch([-2, 0, 2], -2, 2) == [0.0, 0.5, 1.0]\n\n\n"
                "def test_process_batch_clamping_directionality():\n"
                "    # below-range values must land at 0.0; above-range at 1.0\n"
                "    out = process_batch([-100, 100], 0, 10)\n"
                "    assert out == [0.0, 1.0]\n\n\n"
                "def test_process_batch_zero_spread():\n"
                "    # lo == hi forces safe_divide(_, 0) - must return 0.0,\n"
                "    # not raise and not return float('inf').\n"
                "    out = process_batch([1, 2, 3], 5, 5)\n"
                "    assert out == [0.0, 0.0, 0.0]\n\n\n"
                "def test_process_batch_axis_orientation():\n"
                "    # exact midpoint must map to 0.5 (catches axis inversion)\n"
                "    out = process_batch([0, 5, 10], 0, 10)\n"
                "    assert out == [0.0, 0.5, 1.0]\n"
            )
        },
    })

    relevant_files = [mut["root_cause_file"]]
    # The agent must traverse the chain to localize, so we list the full chain
    # but mark only one as ``root_cause``.
    chain = ["multi_pkg/a.py", "multi_pkg/b.py", "multi_pkg/c.py"]
    for f in chain:
        if f not in relevant_files:
            relevant_files.append(f)

    return TaskSpec(
        task_id=task_id,
        repo_id="multi_pkg",
        task_family="causal_hop",
        seed=seed,
        user_prompt=user_prompt,
        formal_prompt=(
            f"Locate and fix the regression in multi_pkg whose root cause is "
            f"{mut['hops']} import-hops away from the public test surface. "
            "Do not change the public API."
        ),
        hidden_formal_spec=(
            "process_batch must map every input value into [0, 1] given the "
            "stated bounds, and must reduce to identity on the bounds endpoints."
        ),
        public_tests=["tests/test_public_causal_hop.py"],
        hidden_validators=hidden_validators,
        mutation_metadata={
            "type": "replace_text",
            "path": mut["path"],
            "old": mut["old"],
            "new": mut["new"],
            "relevant_files": relevant_files,
            "root_cause_file": mut["root_cause_file"],
            "import_hops": mut["hops"],
            "mutation_name": mut["name"],
        },
        oracle_metadata={"patch_type": "reverse_mutation"},
        allowed_files=["multi_pkg/", "tests/test_public_causal_hop.py"],
        protected_files=["pyproject.toml", "pytest.ini"],
        expected_behavior=(
            "process_batch outputs lie in [0, 1] for every value in the input "
            "after clamping, including negative bounds."
        ),
        difficulty={
            "level": "medium",
            "family": "causal_hop",
            "import_hops": mut["hops"],
        },
        reward_config=reward_config,
    )
