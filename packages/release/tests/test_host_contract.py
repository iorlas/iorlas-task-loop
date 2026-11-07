"""The release host contract runs against the independent fake."""
from pathlib import Path

import pytest
from tlkernel.env import Env

from tlrelease.testing import HOST_CASES, FakeReleaseHost, check_host


@pytest.mark.parametrize("case", HOST_CASES)
def test_fake_release_host(tmp_path: Path, case: str):
    env = Env({"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "CLAUDE_CONFIG_DIR": str(tmp_path / "claude"),
               "TASK_LOOP_ACTOR": "contract", "TASK_LOOP_SESSION": "session"})
    check_host(FakeReleaseHost(tmp_path).host, env, tmp_path, case)
