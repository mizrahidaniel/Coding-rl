from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class LocalSandbox:
    def __init__(self, fixture_dir: Path):
        self.fixture_dir = fixture_dir
        self.tempdir = Path(tempfile.mkdtemp(prefix="swegraph_"))
        self.workspace = self.tempdir / "workspace"
        shutil.copytree(fixture_dir, self.workspace)

    def run(self, command: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.workspace,
            shell=True,
            timeout=timeout,
            text=True,
            capture_output=True,
        )

    def teardown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)
