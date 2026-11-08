"""Late patch.dict cleanup must not erase the worker's config home."""

import importlib
import os
from unittest import mock

import pytest

conftest = importlib.import_module("conftest")


@pytest.mark.parametrize("config_home", ["worker-xdg", None])
def test_environment_restored_after_late_cleanup(monkeypatch, tmp_path, config_home):
    if config_home is None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / config_home))
    saved = {k: os.environ.get(k) for k in conftest.ENV}
    protocol = conftest.pytest_runtest_protocol(None, None)
    next(protocol)
    try:
        home = conftest.own_home.__wrapped__()
        next(home)
        patch = mock.patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": str(tmp_path / "patched")})
        patch.start()
        try:
            with pytest.raises(StopIteration):
                next(home)
        finally:
            patch.stop()
        assert "XDG_CONFIG_HOME" not in os.environ
    finally:
        with pytest.raises(StopIteration):
            next(protocol)
    assert {k: os.environ.get(k) for k in conftest.ENV} == saved
