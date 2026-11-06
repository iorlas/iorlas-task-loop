"""Temp paths: only src/taskloop/contracts/scratch.py names a temp location (/tmp, /var/tmp, `tempfile`, TMPDIR). A new site in a change
fails (tests/rules/real/test_ratchets_change.py); use `scratch` / `scratch_dir` (code) or the `workdir` fixture (tests). The scratch
helper's own behaviour is held here."""
import os
from pathlib import Path

from taskloop.contracts import scratch
from taskloop.contracts.env import Env
from taskloop.contracts.paths import default_root


def test_scratch_lives_under_the_config_root_and_never_in_the_system_temp(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert scratch.scratch_root(env) == (default_root(Env(env)) / "tmp").resolve()
    with scratch.scratch(env, "x-") as folder:
        assert folder.is_dir() and folder.parent == scratch.scratch_root(env)
    assert not folder.exists()


def test_scratch_var_moves_the_root(tmp_path):
    assert scratch.scratch_root({scratch.SCRATCH_VAR: str(tmp_path / "s")}) == (tmp_path / "s").resolve()


def test_the_test_identity_is_ours_and_the_host_config_is_off(tmp_path):
    env = scratch.git_identity_env()
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull and env["GIT_AUTHOR_EMAIL"].endswith(".invalid")
    assert "tl test" in scratch.write_git_config(Path(tmp_path)).read_text(encoding="utf-8")
