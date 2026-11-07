"""The suite never reads the machine it runs on: a test's home, config dir and temp dir are its own, and the real agent folders are shut."""

import os
from pathlib import Path

import hermetic
import pytest


class Hermetic:
    def test_home_and_config_are_this_tests_own(self):
        assert os.path.realpath(os.environ["HOME"]) != hermetic.REAL_HOME
        for k in ("HOME", "CODEX_HOME", "DELEGATE_CONFIG_DIR", "TMPDIR"):
            assert os.path.realpath(os.environ[k]).startswith(os.path.realpath(hermetic.ROOT)), k
        assert Path.home() == Path(os.environ["HOME"])

    def test_opening_the_real_config_fails_the_test(self):
        for p in (".config/delegate/state.json", ".codex/auth.json", ".claude/settings.json", ".opencode/x"):
            with pytest.raises(PermissionError), open(os.path.join(hermetic.REAL_HOME, p)):
                pass

    def test_each_test_gets_a_fresh_config_dir(self):
        marker = Path(os.environ["DELEGATE_CONFIG_DIR"]) / "marker"
        assert not marker.exists()  # no earlier test's file is here, whatever the order
        marker.write_text("x")
