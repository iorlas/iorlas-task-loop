"""ChildEnv: the one builder of a child's environment. A virtualenv of ours never reaches the gate (VIRTUAL_ENV, 2026-10-30)."""
import sys
from pathlib import Path
from typing import ClassVar

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters import childenv
from tlkernel.env import Env

BASE = {"PATH": "/venv/bin:/usr/bin", "VIRTUAL_ENV": "/venv", "VIRTUAL_ENV_PROMPT": "x", "PYTHONHOME": "/h", "HOME": "/home/u",
        "TL_SLOT": "s1", "TL_BOGUS": "1", "TASK_LOOP_NOPE": "1", "TL_CHECK_LOG_A": "/log"}


class Venv(Case):
    def test_tool_env_drops_the_virtualenv(self):
        out = childenv.tool_env(BASE, {"X": "1"})
        assert not {"VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "PYTHONHOME"} & out.keys()
        assert out["PATH"] == "/usr/bin"
        assert out["X"] == "1"

    def test_only_registered_engine_names_pass(self):
        out = childenv.tool_env(BASE)
        assert sorted(k for k in out if k.startswith(("TL_", "TASK_LOOP_"))) == ["TL_CHECK_LOG_A", "TL_JUDGE_TL", "TL_SLOT"]

    def test_worker_env_drops_it_too(self):
        out = childenv.child_env_of(BASE)
        assert "VIRTUAL_ENV" not in out
        assert out["PATH"] == "/usr/bin"

    def test_the_process_environment_is_cleaned(self):
        from tlkernel import env as penv  # noqa: PLC0415
        with penv.patched({"VIRTUAL_ENV": "/venv"}):
            assert "VIRTUAL_ENV" not in childenv.tool_env(penv.snapshot().vars)


class Allowlist(Case):
    def test_only_the_listed_names_reach_a_child(self):
        base = {"PATH": "/usr/bin", "HOME": "/h", "USER": "u", "LANG": "C", "LC_ALL": "C", "LC_TIME": "C", "TERM": "xterm", "TMPDIR": "/t",
                "SHELL": "/bin/sh", "TL_SLOT": "s", "AWS_SECRET_ACCESS_KEY": "no", "ANTHROPIC_API_KEY": "no", "GITHUB_TOKEN": "no",
                "SSH_AUTH_SOCK": "/s", "EDITOR": "vi", "PYTHONPATH": "/p"}
        out = childenv.tool_env(base, {"DECLARED": "1"})
        assert sorted(out) == ["DECLARED", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "HOME",
                                       "LANG", "LC_ALL", "LC_TIME", "PATH", "SHELL", "SSH_AUTH_SOCK", "TERM", "TL_JUDGE_TL", "TL_SLOT",
                                       "TMPDIR", "USER"]

    def test_an_empty_environment_gets_only_the_hooks_path(self):
        assert sorted(childenv.tool_env({})) == ["GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "TL_JUDGE_TL"]


class HooksPath(Case):
    """WORKERGIT: every child of tl has git's core.hooksPath set to tl's hooks dir (a default: `git -c` and --no-verify still beat it)."""
    CFG: ClassVar = {"XDG_CONFIG_HOME": "/xdg", "PATH": "/usr/bin"}
    WANT: ClassVar = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/xdg/task-loop/githooks"}

    def test_a_tool_gets_the_three_vars(self):
        out = childenv.tool_env(self.CFG)
        assert {k: out[k] for k in self.WANT} == self.WANT

    def test_a_worker_gets_them_too(self):
        out = childenv.child_env_of(self.CFG)
        assert {k: out[k] for k in self.WANT} == self.WANT

    def test_a_count_already_set_is_extended_not_replaced(self):
        out = childenv.tool_env({**self.CFG, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_VALUE_0": "c"})
        assert (
            (out["GIT_CONFIG_COUNT"], out["GIT_CONFIG_KEY_0"], out["GIT_CONFIG_KEY_1"], out["GIT_CONFIG_VALUE_1"])
            == ("2", "a.b", "core.hooksPath", "/xdg/task-loop/githooks")
        )

    def test_a_child_names_the_tl_of_its_own_install_for_the_pre_push_judge(self):
        assert childenv.tool_env(self.CFG)["TL_JUDGE_TL"] == str(childenv.OWN_TL)
        assert childenv.OWN_TL.name == "tl.py" and childenv.OWN_TL.parent.name == "task-loop"

    def test_the_retired_push_marker_reaches_neither_children_nor_result_keys(self):
        assert "TL_LAND" not in childenv.tool_env({**self.CFG, "TL_LAND": "1"})
        assert "TL_LAND" not in childenv.reaching({**self.CFG, "TL_LAND": "1"})


def test_a_script_runs_without_the_uv_config_of_the_directory_it_starts_in():
    """A worktree's own uv.toml (an index-url) must not decide where tl.py's dependencies come from (tl-7i9k.53, M-055)."""
    argv = childenv.script_argv("/x/tl.py", Env({"UV": "/bin/uv"}))
    assert argv == ["/bin/uv", "run", "--quiet", "--no-config", "--script", "/x/tl.py"]
