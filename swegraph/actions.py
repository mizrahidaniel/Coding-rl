from __future__ import annotations

from pathlib import Path


class ActionAPI:
    def __init__(self, workspace: Path, run_cmd):
        self.workspace = workspace
        self._run_cmd = run_cmd
        self.finished = False

    def run_command(self, command: str) -> dict:
        proc = self._run_cmd(command)
        return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}

    def read_file(self, path: str) -> str:
        return (self.workspace / path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        p = self.workspace / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def apply_patch(self, patch: str) -> dict:
        proc = self._run_cmd(f"apply_patch <<'EOF'\n{patch}\nEOF")
        return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}

    def replace_text(self, path: str, old: str, new: str) -> bool:
        p = self.workspace / path
        txt = p.read_text(encoding="utf-8")
        if old not in txt:
            return False
        p.write_text(txt.replace(old, new), encoding="utf-8")
        return True

    def finish(self) -> None:
        self.finished = True
