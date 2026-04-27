from __future__ import annotations


def run_naive_search_replace(api, task):
    mm = task.mutation_metadata
    if mm.get("type") == "replace_text":
        api.replace_text(mm["path"], mm["new"], mm["old"])
    elif task.task_family == "feature_addition":
        content = api.read_file("todo_cli/core.py")
        if "def list_tasks(tasks: list[dict])" in content:
            content = content.replace(
                "def list_tasks(tasks: list[dict]) -> list[dict]:\n    return tasks\n",
                "def list_tasks(tasks: list[dict], done: bool | None = None) -> list[dict]:\n    if done is None:\n        return tasks\n    return [t for t in tasks if t.get(\"done\") is done]\n",
            )
            api.write_file("todo_cli/core.py", content)
    api.run_command("python -m pytest -q tests")
    api.finish()
