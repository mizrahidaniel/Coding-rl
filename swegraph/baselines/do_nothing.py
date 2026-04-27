from __future__ import annotations


def run_do_nothing(api, task):
    api.run_command("python -m pytest -q tests")
    api.finish()
