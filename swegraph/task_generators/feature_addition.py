from __future__ import annotations

from swegraph.schema import TaskSpec
from swegraph.utils.prompts import generate_prompts


_HIDDEN = '''from todo_cli.core import list_tasks


def test_list_tasks_backwards_compatible():
    tasks = [{"title": "x", "done": False}, {"title": "y", "done": True}]
    assert len(list_tasks(tasks)) == 2


def test_list_tasks_done_filter():
    tasks = [{"title": "x", "done": False}, {"title": "y", "done": True}]
    assert list_tasks(tasks, done=True) == [{"title": "y", "done": True}]
'''


def generate_feature_addition_task(
    task_id: str, seed: int, reward_config: dict[str, float]
) -> TaskSpec:
    repo_id = "todo_cli"
    formal, user, hidden = generate_prompts(repo_id, "feature_addition", "--done flag", seed=seed)
    return TaskSpec(
        task_id=task_id,
        repo_id=repo_id,
        task_family="feature_addition",
        seed=seed,
        user_prompt=user,
        formal_prompt=formal,
        hidden_formal_spec=hidden,
        public_tests=["tests/test_public_feature.py"],
        hidden_validators=[
            {"kind": "unit_tests", "files": {"tests/test_hidden_feature.py": _HIDDEN}},
        ],
        mutation_metadata={
            "type": "feature",
            "path": "todo_cli/core.py",
            "hint": "update list_tasks signature to accept done: bool | None = None",
            "relevant_files": ["todo_cli/core.py"],
            "root_cause_file": "todo_cli/core.py",
        },
        oracle_metadata={
            "patch_type": "replace_text",
            "path": "todo_cli/core.py",
            "old": "def list_tasks(tasks: list[dict]) -> list[dict]:\n    return tasks\n",
            "new": "def list_tasks(tasks: list[dict], done: bool | None = None) -> list[dict]:\n    if done is None:\n        return tasks\n    return [t for t in tasks if t.get(\"done\") is done]\n",
        },
        allowed_files=["todo_cli/core.py", "tests/test_public_feature.py"],
        protected_files=["pyproject.toml", "pytest.ini"],
        expected_behavior="todo list supports done filter flag",
        difficulty={"level": "medium", "family": "feature"},
        reward_config=reward_config,
    )
