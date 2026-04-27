from pathlib import Path

from swegraph.task import generate_tasks, load_task


def test_generate_tasks(tmp_path: Path):
    paths = generate_tasks(30, tmp_path, seed=123)
    assert len(paths) == 30
    families = {load_task(p).task_family for p in paths}
    assert families == {"bug_injection", "config_bug", "feature_addition"}
