def add_task(tasks: list[dict], title: str) -> list[dict]:
    tasks.append({"title": title, "done": False})
    return tasks


def list_tasks(tasks: list[dict]) -> list[dict]:
    return tasks
