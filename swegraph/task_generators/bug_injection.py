from __future__ import annotations

from swegraph.schema import TaskSpec
from swegraph.utils.metamorphic_extract import auto_metamorphic_spec
from swegraph.utils.prompts import generate_prompts


# v1 kept a single hand-authored hidden test file. v2 replaces it with a
# pair of validators:
#   1. a property validator (Hypothesis) that asserts ``percentile`` returns
#      a value bounded by ``min(values)..max(values)`` and is consistent for
#      empty input - hidden, multi-correct-patch friendly,
#   2. a metamorphic validator with relations auto-extracted from the public
#      test source (``boundary_extrema`` for the bounded-output assert in the
#      public test).
#
# A single legacy unit test stays as a regression anchor.
HIDDEN_UNIT_TEST = '''from stats_utils.core import percentile


def test_percentile_interior_index_anchor():
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 70) == 7
'''


_PUBLIC_TEST_SRC = '''from stats_utils.core import percentile


def test_percentile_midpoint():
    assert percentile([1, 2, 3, 4], 75) == 3
'''


_PROPERTY_VALIDATOR = {
    "kind": "property",
    "module": "stats_utils.core",
    "function": "percentile",
    "strategy": [
        {"kind": "lists", "of": "integers", "min_value": -1000, "max_value": 1000, "min_size": 1, "max_size": 30},
        {"kind": "integers", "min_value": 0, "max_value": 100},
    ],
    # property: result is None or lies in [min(args[0]), max(args[0])]
    "assertion": "result is None or (min(args[0]) <= result <= max(args[0]))",
    "max_examples": 120,
}


def generate_bug_injection_task(
    task_id: str, seed: int, reward_config: dict[str, float]
) -> TaskSpec:
    repo_id = "stats_utils"
    formal, user, hidden = generate_prompts(repo_id, "bug_injection", "percentile", seed=seed)

    metamorphic = auto_metamorphic_spec(
        module="stats_utils.core",
        function="percentile",
        strategy=_PROPERTY_VALIDATOR["strategy"],
        public_test_src=_PUBLIC_TEST_SRC,
        # If extraction finds nothing, force boundary_extrema as a safe fallback
        # (the property is also asserted by the standalone PropertyValidator).
        fallback_relations=["boundary_extrema"],
        relation_args={"boundary_extrema": {"arg_index": 0}},
        max_examples=80,
    )

    hidden_validators: list[dict] = [
        _PROPERTY_VALIDATOR,
        {
            "kind": "unit_tests",
            "files": {"tests/test_hidden_bug.py": HIDDEN_UNIT_TEST},
        },
    ]
    if metamorphic is not None:
        hidden_validators.insert(1, metamorphic)

    return TaskSpec(
        task_id=task_id,
        repo_id=repo_id,
        task_family="bug_injection",
        seed=seed,
        user_prompt=user,
        formal_prompt=formal,
        hidden_formal_spec=hidden,
        public_tests=["tests/test_public_bug.py"],
        hidden_validators=hidden_validators,
        mutation_metadata={
            "type": "replace_text",
            "path": "stats_utils/core.py",
            "old": "idx = int(round((len(sorted_vals) - 1) * (p / 100)))",
            "new": "idx = int(round(len(sorted_vals) * (p / 100)))",
            "relevant_files": ["stats_utils/core.py"],
            "root_cause_file": "stats_utils/core.py",
        },
        oracle_metadata={"patch_type": "reverse_mutation"},
        allowed_files=["stats_utils/core.py", "tests/test_public_bug.py"],
        protected_files=["pyproject.toml", "pytest.ini"],
        expected_behavior="percentile handles bounds and interior indexes",
        difficulty={"level": "easy", "family": "bug"},
        reward_config=reward_config,
    )
