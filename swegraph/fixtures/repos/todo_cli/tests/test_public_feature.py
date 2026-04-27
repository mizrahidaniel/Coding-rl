from todo_cli.core import list_tasks


def test_list_tasks_default():
    tasks = [{"title": "a", "done": False}]
    assert list_tasks(tasks) == tasks


def test_list_tasks_done_flag():
    tasks = [{"title": "a", "done": False}, {"title": "b", "done": True}]
    assert list_tasks(tasks, done=True) == [{"title": "b", "done": True}]
