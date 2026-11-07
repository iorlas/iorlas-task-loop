"""Check HOME isolation preserves installed toolchains while withholding the owner's configuration."""
from pathlib import Path
from unittest import mock

import pytest
from support.check_host import CheckHostCase

from taskloop.adapters.git import RealGit
from tlkernel.childenv import CHECK_SECRETS, check_env, check_environment, current_env, delegate_call_env, tool_env
from tlkernel.config import EngineConfig
from tlkernel.env import Env
from tltestkit import procsim
from tltestkit.case import Case


class CheckEnvironmentTest(Case):
    def test_pinned_hooks_are_removed_only_for_checks_and_other_config_is_renumbered(self):
        base = {"GIT_CONFIG_COUNT": "3", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "Suite",
                "GIT_CONFIG_KEY_1": "core.hooksPath", "GIT_CONFIG_VALUE_1": "/global/hooks",
                "GIT_CONFIG_KEY_2": "protocol.file.allow", "GIT_CONFIG_VALUE_2": "always",
                "GIT_CONFIG_GLOBAL": "/suite/gitconfig", "GIT_CONFIG_NOSYSTEM": "1"}
        pinned = RealGit(Env(base)).git_env("/repo")
        for scratch in (False, True):
            with self.subTest(scratch=scratch), check_environment(pinned, scratch_home=scratch) as out:
                config = {k: v for k, v in out.items() if k.startswith("GIT_CONFIG_")}
                assert config == {"GIT_CONFIG_COUNT": "3", "GIT_CONFIG_KEY_0": "user.name",
                                          "GIT_CONFIG_VALUE_0": "Suite", "GIT_CONFIG_KEY_1": "protocol.file.allow",
                                          "GIT_CONFIG_VALUE_1": "always", "GIT_CONFIG_KEY_2": "core.fsmonitor",
                                          "GIT_CONFIG_VALUE_2": "false", "GIT_CONFIG_GLOBAL": "/suite/gitconfig",
                                          "GIT_CONFIG_NOSYSTEM": "1"}
        assert "core.hooksPath" in pinned.values()
        assert "core.hooksPath" in tool_env(base).values()

    def test_a_call_to_delegate_carries_no_depth_mark_but_any_other_child_does(self):
        env = Env({"PATH": "/bin", "CLAUDE_CONFIG_DIR": "/session"})
        assert current_env(env)["DELEGATE_DEPTH"] == "1"
        out = delegate_call_env(env, {"X": "1"})
        assert "CLAUDE_CONFIG_DIR" not in out
        assert "DELEGATE_DEPTH" not in out
        assert (out["TASK_LOOP_WORKER"], out["X"]) == ("1", "1")

    def test_profile_defaults_to_the_callers_home(self):
        assert not EngineConfig().check_scratch_home

    def test_default_mode_preserves_home_and_config_without_creating_a_directory(self):
        base = {"HOME": "/owner", "XDG_CONFIG_HOME": "/config", "XDG_DATA_HOME": "/data",
                "XDG_STATE_HOME": "/state", "MISE_CONFIG_DIR": "/mise", "XDG_CACHE_HOME": "/cache", "XDG_RUNTIME_DIR": "/runtime",
                **dict.fromkeys(CHECK_SECRETS, "parent-secret"), "GIT_CREDENTIAL_HELPER": "secret"}
        extra = {"XDG_CONFIG_HOME": "/declared-config", **dict.fromkeys(CHECK_SECRETS, "declared-secret")}
        with (mock.patch("tlkernel.childenv.tempfile.TemporaryDirectory") as temporary,
              check_environment(base, extra, scratch_home=False) as out):
            expected = {k: v for k, v in base.items() if k not in CHECK_SECRETS and not k.startswith("GIT_CREDENTIAL")}
            expected["XDG_CONFIG_HOME"] = "/declared-config"
            assert {k: out[k] for k in expected} == expected
            assert not CHECK_SECRETS & out.keys()
            assert "GIT_CREDENTIAL_HELPER" not in out
            assert out["UV_CACHE_DIR"] == "/cache/uv"
            assert out["MISE_DATA_DIR"] == "/data/mise"
        temporary.assert_not_called()

    def test_default_mode_keeps_absent_config_names_absent_and_honors_declared_home(self):
        out = check_env({"HOME": "/owner"}, {"HOME": "/declared"}, home=None)
        assert out["HOME"] == "/declared"
        assert not {"XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "MISE_CONFIG_DIR"} & out.keys()

    def test_builder_overrides_home_and_config_after_declared_env(self):
        base = {"HOME": "/owner", "PATH": "/tools/bin", "SSH_AUTH_SOCK": "/agent", "GH_TOKEN": "parent-secret"}
        extra = {**dict.fromkeys(CHECK_SECRETS, "declared-secret"), "HOME": "/owner", "XDG_CONFIG_HOME": "/owner/config",
                 "XDG_DATA_HOME": "/owner/data", "XDG_STATE_HOME": "/owner/state", "MISE_CONFIG_DIR": "/owner/mise",
                 "GIT_CREDENTIAL_HELPER": "secret", "MODE": "test"}
        out = check_env(base, extra, home="/scratch")
        assert not CHECK_SECRETS & out.keys()
        assert "GIT_CREDENTIAL_HELPER" not in out
        assert out["HOME"] == "/scratch"
        assert out["XDG_CONFIG_HOME"] == "/scratch/.config"
        assert out["XDG_DATA_HOME"] == "/scratch/.local/share"
        assert out["XDG_STATE_HOME"] == "/scratch/.local/state"
        assert out["MISE_CONFIG_DIR"] == "/scratch/.config/mise"
        assert (out["MODE"], out["PATH"]) == ("test", "/tools/bin")
        assert base["HOME"] == "/owner"
        assert tool_env(base)["SSH_AUTH_SOCK"] == "/agent"

    def test_cache_defaults_point_to_the_original_toolchain_locations(self):
        out = check_env({"HOME": "/owner"}, {"HOME": "/ignored"}, home="/scratch")
        expected = {"XDG_CACHE_HOME": "/owner/.cache", "UV_CACHE_DIR": "/owner/.cache/uv",
                    "UV_PYTHON_INSTALL_DIR": "/owner/.local/share/uv/python",
                    "MISE_CACHE_DIR": "/owner/.cache/mise",
                    "MISE_DATA_DIR": "/owner/.local/share/mise", "MISE_STATE_DIR": "/owner/.local/state/mise"}
        assert {k: out[k] for k in expected} == expected

    def test_explicit_cache_paths_survive_and_slot_overrides_win(self):
        caches = {"XDG_CACHE_HOME": "/cache", "UV_CACHE_DIR": "/uv", "UV_PYTHON_INSTALL_DIR": "/python",
                  "MISE_CACHE_DIR": "/mise-cache",
                  "MISE_DATA_DIR": "/mise-data", "MISE_STATE_DIR": "/mise-state"}
        for home in (None, "/scratch"):
            with self.subTest(home=home):
                out = check_env({"HOME": "/owner", **caches, "MISE_SECRET_TOKEN": "secret"},
                                {"UV_CACHE_DIR": "/slot/uv"}, home=home)
                assert {k: out[k] for k in caches} == {**caches, "UV_CACHE_DIR": "/slot/uv"}
                assert "MISE_SECRET_TOKEN" not in out

    def test_each_execution_has_a_private_home_and_cleans_up_on_error(self):
        with check_environment({"HOME": "/owner"}, scratch_home=True) as first:
            home = Path(first["HOME"])
            assert home.is_dir()
            assert home.stat().st_mode & 0o777 == 0o700
            (home / "state").write_text("private")
            with (pytest.raises(RuntimeError, match="child failed"),
                  check_environment({"HOME": "/owner"}, scratch_home=True) as second):
                other = Path(second["HOME"])
                assert home != other
                assert not (other / "state").exists()
                raise RuntimeError("child failed")
            assert not other.exists()
        assert not home.exists()

class EngineCheckEnvironmentTest(CheckHostCase):
    def test_engine_checks_and_fixes_cannot_restore_host_credentials(self):
        seen = []

        def probe(cwd, env):
            home = Path(env["HOME"])
            assert home.is_dir()
            assert not CHECK_SECRETS & env.keys()
            assert env["XDG_CONFIG_HOME"] == str(home / ".config")
            seen.append(home)
            return 0, "isolated"

        cmd = procsim.fake("probe-check-home", probe)
        eng = self.checks_engine(check_scratch_home=True,
                                 checks=[{"id": "probe", "cmd": cmd, "env": {"GH_TOKEN": "secret", "HOME": "/owner"}}])
        for what in ("check", "check fix"):
            rc, _ = eng.sh(["probe-check-home"], what=what, env={"SSH_AUTH_SOCK": "/agent", "HOME": "/owner"})
            assert rc == 0
        results = eng.run_checks({"checks": [], "files": []}, "s")
        assert results[0].exit == 0
        assert len(seen) == 3
        assert len(set(seen)) == 3
        assert not any(home.exists() for home in seen)
