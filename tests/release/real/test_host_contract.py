"""The same release host contract runs against the real shell binding."""
from pathlib import Path

import pytest

from taskloop.app.launch.release_host import release_host
from tlkernel.env import Env
from tlrelease.testing import HOST_CASES, check_host
from tltestkit.checked import run_checked


@pytest.mark.parametrize("case", HOST_CASES)
def test_real_release_host(workdir: Path, case: str):
    run_checked(["git", "init", "-q", str(workdir)], workdir)
    env = Env({"XDG_CONFIG_HOME": str(workdir / "cfg"), "CLAUDE_CONFIG_DIR": str(workdir / "claude"),
               "TASK_LOOP_ACTOR": "contract", "TASK_LOOP_SESSION": "session"})
    check_host(release_host(), env, workdir, case)
