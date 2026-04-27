from __future__ import annotations

from swegraph.schema import TaskSpec
from swegraph.utils.prompts import generate_prompts


def generate_bug_injection_task(task_id: str, seed: int, reward_config: dict[str, float]) -> TaskSpec:
    repo_id = "stats_utils"
    formal, user, hidden = generate_prompts(repo_id, "bug_injection", "percentile")
    hidden_test = """from stats_utils.core import percentile\n\n\ndef test_percentile_empty_none():\n    assert percentile([], 50) is None\n\n\ndef test_percentile_bounds():\n    data = [1, 2, 3, 4]\n    assert percentile(data, 0) == 1\n    assert percentile(data, 100) == 4\n"""
    return TaskSpec(
        task_id=task_id,
        repo_id=repo_id,
        task_family="bug_injection",
        seed=seed,
        user_prompt=user,
        formal_prompt=formal,
        hidden_formal_spec=hidden,
        public_tests=["tests/test_public_bug.py"],
        hidden_tests={"tests/test_hidden_bug.py": hidden_test},
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
        expected_behavior="percentile handles bounds and empty input",
        difficulty={"level": "easy", "family": "bug"},
        reward_config=reward_config,
    )
