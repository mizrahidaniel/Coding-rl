from __future__ import annotations


def run_oracle_patch(api, task):
    if task.oracle_metadata.get("patch_type") == "reverse_mutation":
        mm = task.mutation_metadata
        api.replace_text(mm["path"], mm["new"], mm["old"])
    elif task.oracle_metadata.get("patch_type") == "replace_text":
        om = task.oracle_metadata
        api.replace_text(om["path"], om["old"], om["new"])
    api.run_command("python -m pytest -q tests")
    api.finish()
