from __future__ import annotations

from swegraph.schema import TaskSpec
from swegraph.utils.prompts import generate_prompts


# Hidden tests deliberately probe interior indexes (not just p=0/100 which
# hit the early-return paths). p=70 over a 10-element list separates the
# correct (len-1)*p/100 formula from the buggy len*p/100 form.
HIDDEN_TEST = '''from stats_utils.core import percentile


def test_percentile_empty_returns_none():
    assert percentile([], 50) is None


def test_percentile_bounds():
    data = [1, 2, 3, 4]
    assert percentile(data, 0) == 1
    assert percentile(data, 100) == 4


def test_percentile_midpoint_small():
    assert percentile([1, 2, 3, 4], 75) == 3


def test_percentile_interior_index():
    # (10-1)*0.7 = 6.3 -> idx 6 -> value 7
    # buggy variant 10*0.7 = 7 -> idx 7 -> value 8
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 70) == 7


def test_percentile_does_not_overflow():
    # buggy variant would index past the end on len=4 at p=80:
    # 4*0.8 = 3.2 -> idx 3 -> value 4
    # correct: (4-1)*0.8 = 2.4 -> idx 2 -> value 3
    assert percentile([1, 2, 3, 4], 80) == 3
'''


def generate_bug_injection_task(
    task_id: str, seed: int, reward_config: dict[str, float]
) -> TaskSpec:
    repo_id = "stats_utils"
    formal, user, hidden = generate_prompts(repo_id, "bug_injection", "percentile", seed=seed)
    return TaskSpec(
        task_id=task_id,
        repo_id=repo_id,
        task_family="bug_injection",
        seed=seed,
        user_prompt=user,
        formal_prompt=formal,
        hidden_formal_spec=hidden,
        public_tests=["tests/test_public_bug.py"],
        hidden_tests={"tests/test_hidden_bug.py": HIDDEN_TEST},
        mutation_metadata={
            "type": "replace_text",
            "path": "stats_utils/core.py",
            "old": "idx = int(round((len(sorted_vals) - 1) * (p / 100)))",
            "new": "idx = int(round(len(sorted_vals) * (p / 100)))",
            "relevant_files": ["stats_utils/core.py"],
        },
        oracle_metadata={"patch_type": "reverse_mutation"},
        allowed_files=["stats_utils/core.py", "tests/test_public_bug.py"],
        protected_files=["pyproject.toml", "pytest.ini"],
        expected_behavior="percentile handles bounds and interior indexes",
        difficulty={"level": "easy", "family": "bug"},
        reward_config=reward_config,
    )
