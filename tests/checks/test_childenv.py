"""Check HOME isolation preserves installed toolchains while withholding the owner's configuration."""
import unittest
from pathlib import Path
from unittest import mock

from support import engine_case as te
from support import procsim

from taskloop.adapters.childenv import CHECK_SECRETS, check_env, check_environment, tool_env
from taskloop.app.checks.container import Box
from taskloop.app.checks.execution import ReadyExecution
from taskloop.contracts.checks import Check
from taskloop.contracts.env import Env
from taskloop.contracts.ids import CheckId
from taskloop.contracts.runkey import Digest


class CheckEnvironmentTest(unittest.TestCase):
    def test_builder_overrides_home_and_config_after_declared_env(self):
        base = {"HOME": "/owner", "PATH": "/tools/bin", "SSH_AUTH_SOCK": "/agent", "GH_TOKEN": "parent-secret"}
        extra = {**dict.fromkeys(CHECK_SECRETS, "declared-secret"), "HOME": "/owner", "XDG_CONFIG_HOME": "/owner/config",
                 "XDG_DATA_HOME": "/owner/data", "XDG_STATE_HOME": "/owner/state", "MISE_CONFIG_DIR": "/owner/mise",
                 "GIT_CREDENTIAL_HELPER": "secret", "MODE": "test"}
        out = check_env(base, extra, home="/scratch")
        self.assertFalse(CHECK_SECRETS & out.keys())
        self.assertNotIn("GIT_CREDENTIAL_HELPER", out)
        self.assertEqual(out["HOME"], "/scratch")
        self.assertEqual(out["XDG_CONFIG_HOME"], "/scratch/.config")
        self.assertEqual(out["XDG_DATA_HOME"], "/scratch/.local/share")
        self.assertEqual(out["XDG_STATE_HOME"], "/scratch/.local/state")
        self.assertEqual(out["MISE_CONFIG_DIR"], "/scratch/.config/mise")
        self.assertEqual((out["MODE"], out["PATH"]), ("test", "/tools/bin"))
        self.assertEqual(base["HOME"], "/owner")
        self.assertEqual(tool_env(base)["SSH_AUTH_SOCK"], "/agent")

    def test_cache_defaults_point_to_the_original_toolchain_locations(self):
        out = check_env({"HOME": "/owner"}, {"HOME": "/ignored"}, home="/scratch")
        expected = {"XDG_CACHE_HOME": "/owner/.cache", "UV_CACHE_DIR": "/owner/.cache/uv",
                    "UV_PYTHON_INSTALL_DIR": "/owner/.local/share/uv/python", "DOTNET_CLI_HOME": "/owner",
                    "NUGET_PACKAGES": "/owner/.nuget/packages", "MISE_CACHE_DIR": "/owner/.cache/mise",
                    "MISE_DATA_DIR": "/owner/.local/share/mise", "MISE_STATE_DIR": "/owner/.local/state/mise"}
        self.assertEqual({k: out[k] for k in expected}, expected)

    def test_explicit_cache_paths_survive_and_slot_overrides_win(self):
        caches = {"XDG_CACHE_HOME": "/cache", "UV_CACHE_DIR": "/uv", "UV_PYTHON_INSTALL_DIR": "/python",
                  "DOTNET_CLI_HOME": "/dotnet", "NUGET_PACKAGES": "/nuget", "MISE_CACHE_DIR": "/mise-cache",
                  "MISE_DATA_DIR": "/mise-data", "MISE_STATE_DIR": "/mise-state"}
        out = check_env({"HOME": "/owner", **caches, "MISE_SECRET_TOKEN": "secret"},
                        {"DOTNET_CLI_HOME": "/slot/dotnet"}, home="/scratch")
        self.assertEqual({k: out[k] for k in caches}, {**caches, "DOTNET_CLI_HOME": "/slot/dotnet"})
        self.assertNotIn("MISE_SECRET_TOKEN", out)

    def test_each_execution_has_a_private_home_and_cleans_up_on_error(self):
        with check_environment({"HOME": "/owner"}) as first:
            home = Path(first["HOME"])
            self.assertTrue(home.is_dir())
            self.assertEqual(home.stat().st_mode & 0o777, 0o700)
            (home / "state").write_text("private")
            with self.assertRaisesRegex(RuntimeError, "child failed"), check_environment({"HOME": "/owner"}) as second:
                other = Path(second["HOME"])
                self.assertNotEqual(home, other)
                self.assertFalse((other / "state").exists())
                raise RuntimeError("child failed")
            self.assertFalse(other.exists())
        self.assertFalse(home.exists())

    def test_container_forwarding_scrubs_declared_credentials_and_host_home(self):
        host = mock.Mock()
        host.env = Env({"HOME": "/owner", "SSH_AUTH_SOCK": "/agent"})
        host.bead_env = {"TL_SLOT": "check"}
        host.run_dir = Path("/run/check")
        box = Box(host, host.spawner)
        check = Check(id=CheckId("probe"), cmd="true", container=True)
        with mock.patch.object(box, "resolve", return_value=ReadyExecution(Digest("image"), "image")):
            argv, _ = box.plan(check, ["true"], {"HOME": "/owner", "GH_TOKEN": "secret", "GIT_SSH_COMMAND": "ssh",
                                                     "MODE": "test"})
        env = dict(argv[n + 1].split("=", 1) for n, word in enumerate(argv) if word == "--env")
        self.assertEqual(env, {"TL_SLOT": "check", "MODE": "test"})


class EngineCheckEnvironmentTest(te.EngineTest):
    def test_engine_checks_and_fixes_cannot_restore_host_credentials(self):
        seen = []

        def probe(cwd, env):
            home = Path(env["HOME"])
            self.assertTrue(home.is_dir())
            self.assertFalse(CHECK_SECRETS & env.keys())
            self.assertEqual(env["XDG_CONFIG_HOME"], str(home / ".config"))
            seen.append(home)
            return 0, "isolated"

        cmd = procsim.fake("probe-check-home", probe)
        eng = self.checks_engine(checks=[{"id": "probe", "cmd": cmd, "env": {"GH_TOKEN": "secret", "HOME": "/owner"}}])
        for what in ("check", "check fix"):
            rc, _ = eng.sh(["probe-check-home"], what=what, env={"SSH_AUTH_SOCK": "/agent", "HOME": "/owner"})
            self.assertEqual(rc, 0)
        results = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual(results[0].exit, 0)
        self.assertEqual(len(seen), 3)
        self.assertEqual(len(set(seen)), 3)
        self.assertFalse(any(home.exists() for home in seen))
