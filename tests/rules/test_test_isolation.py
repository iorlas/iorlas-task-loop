"""Every test process uses scratch home and config directories instead of the caller's."""
import os
from pathlib import Path


def test_home_and_config_are_isolated():
    for name, original in (("HOME", "TL_TEST_REAL_HOME"), ("XDG_CONFIG_HOME", "TL_TEST_REAL_CONFIG_HOME")):
        assert Path(os.environ[name]).resolve() != Path(os.environ[original]).resolve()
