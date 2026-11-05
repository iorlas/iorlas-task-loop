"""dev/runtests.py gives the tests a clean git environment: a release passes GIT_CONFIG_COUNT/KEY_n/VALUE_n (core.hooksPath = tl's hooks),
and inherited they would fire tl's pre-push judge in the tests' throwaway repos."""
import os
from unittest import mock

import runtests
import support.paths  # noqa: F401


def test_isolated_env_drops_the_git_config_variables(tmp_path):
    given = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/hooks", "GIT_DIR": "/x", "KEEP": "1"}
    with mock.patch.dict(os.environ, given):
        env = runtests.isolated_env(tmp_path)
    assert not [k for k in env if k.startswith("GIT_CONFIG_") or k == "GIT_DIR"]
    assert env["KEEP"] == "1"
    assert env["HOME"] == str(tmp_path)
