"""Temp paths, ratchet mode: only src/taskloop/contracts/scratch.py names a temp location (/tmp, /var/tmp, `tempfile`, TMPDIR).
Today's sites
are the baseline (temp_baseline.json, per directory); a new one fails. Use `scratch` / `scratch_dir` (code) or the `workdir`
fixture (tests)."""
import json
import os
from pathlib import Path

from rules import temp_ratchet
from taskloop.contracts import scratch


def test_no_new_temp_site():
    base = json.loads(temp_ratchet.BASELINE.read_text(encoding="utf-8"))
    bad = temp_ratchet.grown(temp_ratchet.count_tree(), base)
    assert bad == [], ("a new /tmp, tempfile or TMPDIR site: ask contracts/scratch.py (scratch / scratch_dir; tests: the workdir fixture): "
                       + "; ".join(bad))


def test_grown_names_only_increases():
    assert temp_ratchet.grown({"a": 2, "b": 1}, {"a": 2}) == ["b: 1 (baseline 0)"]


def test_scratch_lives_under_the_cache_root_and_never_in_the_system_temp_or_the_config_dir(tmp_path):
    env = {"XDG_CACHE_HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "cfg")}
    assert scratch.scratch_root(env) == (tmp_path / "task-loop" / "tmp").resolve()
    with scratch.scratch(env, "x-") as folder:
        assert folder.is_dir() and folder.parent == scratch.scratch_root(env)
    assert not folder.exists()


def test_scratch_var_moves_the_root(tmp_path):
    assert scratch.scratch_root({scratch.SCRATCH_VAR: str(tmp_path / "s")}) == (tmp_path / "s").resolve()


def test_the_test_identity_is_ours_and_the_host_config_is_off(tmp_path):
    env = scratch.git_identity_env()
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull and env["GIT_AUTHOR_EMAIL"].endswith(".invalid")
    assert "tl test" in scratch.write_git_config(Path(tmp_path)).read_text(encoding="utf-8")
