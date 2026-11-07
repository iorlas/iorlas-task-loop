"""dev/runtests.py gives the tests a clean git environment: a release passes GIT_CONFIG_COUNT/KEY_n/VALUE_n (core.hooksPath = tl's hooks),
and inherited they would fire tl's pre-push judge in the tests' throwaway repos."""
import io
import os
import sys
from unittest import mock

import pytest
import runtests


def test_isolated_env_drops_the_git_config_variables(tmp_path):
    given = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/hooks", "GIT_DIR": "/x", "KEEP": "1"}
    with mock.patch.dict(os.environ, given):
        env = runtests.isolated_env(tmp_path)
    assert not [k for k in env if k.startswith("GIT_CONFIG_") or k == "GIT_DIR"]
    assert env["KEEP"] == "1"
    assert env["HOME"] == str(tmp_path)


@pytest.mark.parametrize("configured, exists", [("/custom/uv", True), ("/custom/uv", False), (None, True), (None, False), ("", True)])
def test_isolated_env_preserves_the_callers_uv_cache(tmp_path, monkeypatch, configured, exists):
    real_home = tmp_path / "caller"
    cache = real_home / ".cache" / "uv"
    if exists:
        cache.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    if configured is not None:
        monkeypatch.setenv("UV_CACHE_DIR", configured)
    env = runtests.isolated_env(tmp_path / "isolated")
    assert env.get("UV_CACHE_DIR") == (configured or (str(cache) if exists else None))
    assert env["HOME"] == str(tmp_path / "isolated")


def _res(timed_out):
    return runtests.stream_proc.Result(returncode=None, signal=9, timed_out=timed_out, pid=1, pgid=1, start=None, secs=1.0)


def test_a_pytest_run_silent_past_the_idle_limit_is_stopped_and_named(tmp_path):
    seen = {}

    def run(argv, **kw):
        seen.update(kw)
        return _res("idle")
    err = io.StringIO()
    with mock.patch.object(runtests.stream_proc, "run", run), mock.patch.object(sys, "stderr", err):
        code = runtests.pytest(tmp_path, {}, "not serial", ["tests/x"], 1)
    assert code == 124
    assert seen["idle"] == runtests.IDLE_S < seen["timeout"]
    assert "no output for" in err.getvalue()
