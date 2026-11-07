"""delegate-e8z: a codex worker's uv never touches ~/.cache/uv (outside the sandbox) and stays offline while the sandbox has no network."""

import os
import shutil
import subprocess
from pathlib import Path

import hermetic  # noqa: F401  (a home of its own for every test)
import pytest
from support.procsim import real_proc

from delegate.app import decide
from tltestkit.tmpdir import TemporaryDirectory


class CodexUvEnv:



    @real_proc("delegate: a worker, git or CLI process")
    @pytest.mark.skipif(not shutil.which("uv"), reason="uv is not installed")
    def test_uv_run_succeeds_with_a_cold_cache_offline(self):
        with TemporaryDirectory() as d:
            e = decide.codex_env({k: v for k, v in os.environ.items() if not k.startswith("UV_")}, d, "workspace-write")
            r = subprocess.run(
                ["uv", "run", "python", "-c", "pass"], cwd=d, env=e, capture_output=True, text=True, timeout=120, check=False
            )
            assert r.returncode == 0, r.stderr
            assert (Path(d) / ".task" / "uv-cache").is_dir()
