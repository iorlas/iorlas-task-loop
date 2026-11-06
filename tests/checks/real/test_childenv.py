"""Real check children retain the caller's HOME by default and isolate it when the profile opts in."""
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.argv_checks import ArgvChecks
from support.case import Case
from support.checked import run_checked
from support.tlmain import tl_main
from support.tmpdir import TemporaryDirectory

from taskloop.adapters import childenv
from taskloop.adapters.childenv import CHECK_SECRETS
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.run.shell import Shell
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.env import Env
from taskloop.contracts.ports import CheckSpec


class CheckHomeCanaryTest(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner = self.root / "owner"
        for rel in (".ssh", ".config/gh", ".claude", ".config/task-loop"):
            directory = self.owner / rel
            directory.mkdir(parents=True)
            (directory / "canary").write_text("synthetic owner state")
        self.output = self.root / "seen.json"
        self.probe = (
            "import json,os,pathlib; h=pathlib.Path.home(); "
            "seen={'home':str(h),'private':h.is_dir(),'env':dict(os.environ),"
            "'canaries':[str(p) for p in h.rglob('canary')]}; "
            f"pathlib.Path({str(self.output)!r}).write_text(json.dumps(seen))"
        )

    def assert_isolated(self):
        seen = json.loads(self.output.read_text())
        assert seen["home"] != str(self.owner)
        assert seen["private"]
        assert seen["canaries"] == []
        assert not CHECK_SECRETS & seen["env"].keys()
        assert not Path(seen["home"]).exists()
        assert (self.owner / ".ssh/canary").is_file()

    def assert_owner_home(self):
        seen = json.loads(self.output.read_text())
        assert seen["home"] == str(self.owner)
        assert str(self.owner / "canary") in seen["canaries"]
        assert not CHECK_SECRETS & seen["env"].keys()
        assert not any(name.startswith("GIT_CREDENTIAL") for name in seen["env"])

    def test_standalone_argv_check_defaults_to_owner_home_and_strips_secrets(self):
        (self.owner / "canary").write_text("synthetic toolchain state")
        secrets = {**dict.fromkeys(CHECK_SECRETS, "synthetic-secret"), "GIT_CREDENTIAL_HELPER": "synthetic-helper"}
        env = Env({"HOME": str(self.owner), **secrets})
        result = ArgvChecks(env).run(CheckSpec(argv=[sys.executable, "-c", self.probe], cwd=str(self.root), env=secrets))
        assert result.exit == 0, result.out
        self.assert_owner_home()

    def test_standalone_argv_check_cannot_find_owner_state_through_home(self):
        env = Env({"HOME": str(self.owner), "SSH_AUTH_SOCK": "/synthetic-agent"})
        result = ArgvChecks(env, scratch_home=True).run(CheckSpec(argv=[sys.executable, "-c", self.probe], cwd=str(self.root),
                                                               env={"HOME": str(self.owner), "GH_TOKEN": "synthetic-token"}))
        assert result.exit == 0, result.out
        self.assert_isolated()

    def test_real_shell_checks_and_fixes_use_the_scrubbed_environment(self):
        env = Env({"HOME": str(self.owner), "SSH_AUTH_SOCK": "/synthetic-agent", "GIT_SSH_COMMAND": "synthetic-ssh"})
        host = SimpleNamespace(env=env, bead_env={}, spawner=RealSpawner(env), wt=self.root,
                               halt=threading.Event(), log=mock.Mock(), halt_point=mock.Mock(), cfg=EngineConfig(check_scratch_home=True))
        host.log.next_id.return_value = "m1"
        for what in ("check", "check fix"):
            with self.subTest(what=what), mock.patch.object(childenv, "check_env", wraps=childenv.check_env) as builder:
                rc, tail = Shell(host).run([sys.executable, "-c", self.probe], what=what,
                                          env={"HOME": str(self.owner), "SSH_AUTH_SOCK": "/declared-agent",
                                               "GIT_SSH_COMMAND": "declared-ssh"})
                assert rc == 0, tail
                self.assert_isolated()
                seen = json.loads(self.output.read_text())
                assert seen["home"] == builder.call_args.kwargs["home"]
                assert seen["env"]["UV_CACHE_DIR"] == str(self.owner / ".cache/uv")

    def test_real_shell_checks_and_fixes_default_to_owner_home_and_strip_secrets(self):
        (self.owner / "canary").write_text("synthetic toolchain state")
        secrets = {**dict.fromkeys(CHECK_SECRETS, "synthetic-secret"), "GIT_CREDENTIAL_HELPER": "synthetic-helper"}
        env = Env({"HOME": str(self.owner), **secrets})
        host = SimpleNamespace(env=env, bead_env={}, spawner=RealSpawner(env), wt=self.root, cfg=EngineConfig(),
                               halt=threading.Event(), log=mock.Mock(), halt_point=mock.Mock())
        host.log.next_id.return_value = "m1"
        for what in ("check", "check fix"):
            with self.subTest(what=what):
                rc, tail = Shell(host).run([sys.executable, "-c", self.probe], what=what, env=secrets)
                assert rc == 0, tail
                self.assert_owner_home()

    def test_cli_gate_in_real_git_checkout_cannot_find_owner_state_through_home(self):
        self.run_cli_gate(scratch_home=True)
        self.assert_isolated()

    def test_cli_gate_defaults_to_owner_home_and_strips_secrets(self):
        (self.owner / "canary").write_text("synthetic toolchain state")
        self.run_cli_gate()
        self.assert_owner_home()

    def run_cli_gate(self, *, scratch_home=False):
        repo = self.root / "repo"
        repo.mkdir()
        checks = [{"id": "probe", "argv": [sys.executable, "-c", self.probe], "run": "gate",
                   "env": {"HOME": str(self.owner), **dict.fromkeys(CHECK_SECRETS, "synthetic-secret"),
                           "GIT_CREDENTIAL_HELPER": "synthetic-helper"}}]
        engine: dict[str, object] = {"base": "main", "checks": checks}
        if scratch_home:
            engine["check_scratch_home"] = True
        (repo / ".task-loop.json").write_text(json.dumps({"engine": engine}))
        for args in (("init", "-q", "-b", "main"), ("add", ".task-loop.json"), ("commit", "-qm", "canary")):
            run_checked(["git", "-c", "user.name=Canary", "-c", "user.email=canary@example.invalid", *args], repo)
        ran = tl_main("check", "--repo", str(repo), "--all", "probe", cwd=repo,
                      env={"HOME": str(self.owner), "XDG_CONFIG_HOME": str(self.root / "config"),
                           "SSH_AUTH_SOCK": "/synthetic-agent", "GIT_SSH_COMMAND": "synthetic-ssh"})
        assert ran.returncode == 0, ran.stdout + ran.stderr
