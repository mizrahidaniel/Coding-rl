from __future__ import annotations

from swegraph.schema import TaskSpec
from swegraph.utils.prompts import generate_prompts


_HIDDEN = '''from csv_tool.core import parse_csv


def test_parse_csv_default_delimiter_still_works():
    rows = parse_csv("a,b\\n1,2\\n")
    assert rows == [{"a": "1", "b": "2"}]


def test_parse_csv_delimiter_key_still_works():
    cfg = {"delimiter": ";"}
    rows = parse_csv("a;b\\n1;2\\n", config=cfg)
    assert rows == [{"a": "1", "b": "2"}]
'''


def generate_config_bug_task(
    task_id: str, seed: int, reward_config: dict[str, float]
) -> TaskSpec:
    repo_id = "csv_tool"
    formal, user, hidden = generate_prompts(repo_id, "config_bug", "CSV delimiter", seed=seed)
    return TaskSpec(
        task_id=task_id,
        repo_id=repo_id,
        task_family="config_bug",
        seed=seed,
        user_prompt=user,
        formal_prompt=formal,
        hidden_formal_spec=hidden,
        public_tests=["tests/test_public_config.py"],
        hidden_validators=[
            {"kind": "unit_tests", "files": {"tests/test_hidden_config.py": _HIDDEN}},
        ],
        mutation_metadata={
            "type": "replace_text",
            "path": "csv_tool/core.py",
            "old": "delimiter = (config or {}).get(\"delimiter\", \",\")",
            "new": "delimiter = (config or {}).get(\"delim\", \",\")",
            "relevant_files": ["csv_tool/core.py"],
            "root_cause_file": "csv_tool/core.py",
        },
        oracle_metadata={"patch_type": "reverse_mutation"},
        allowed_files=["csv_tool/core.py", "tests/test_public_config.py"],
        protected_files=["pyproject.toml", "pytest.ini"],
        expected_behavior="config delimiter key works in all parser paths",
        difficulty={"level": "easy", "family": "config"},
        reward_config=reward_config,
    )
