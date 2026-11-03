"""Real check children resolve ~ to a private HOME, never the fake owner's credential and configuration canaries."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.tlmain import tl_main

from taskloop.adapters import childenv
from taskloop.adapters.checks_argv import ArgvChecks
from taskloop.adapters.childenv import CHECK_SECRETS
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.run.shell import Shell
from taskloop.contracts.env import Env
from taskloop.contracts.ports import CheckSpec


class CheckHomeCanaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
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
        self.assertNotEqual(seen["home"], str(self.owner))
        self.assertTrue(seen["private"])
        self.assertEqual(seen["canaries"], [])
        self.assertFalse(CHECK_SECRETS & seen["env"].keys())
        self.assertFalse(Path(seen["home"]).exists())
        self.assertTrue((self.owner / ".ssh/canary").is_file())

    def test_standalone_argv_check_cannot_find_owner_state_through_home(self):
        env = Env({"HOME": str(self.owner), "SSH_AUTH_SOCK": "/synthetic-agent"})
        result = ArgvChecks(env).run(CheckSpec(argv=[sys.executable, "-c", self.probe], cwd=str(self.root),
                                              env={"HOME": str(self.owner), "GH_TOKEN": "synthetic-token"}))
        self.assertEqual(result.exit, 0, result.out)
        self.assert_isolated()

    def test_real_shell_checks_and_fixes_use_the_scrubbed_environment(self):
        env = Env({"HOME": str(self.owner), "SSH_AUTH_SOCK": "/synthetic-agent", "GIT_SSH_COMMAND": "synthetic-ssh"})
        host = SimpleNamespace(env=env, bead_env={}, spawner=RealSpawner(env), wt=self.root,
                               halt=threading.Event(), log=mock.Mock(), halt_point=mock.Mock())
        host.log.next_id.return_value = "m1"
        for what in ("check", "check fix"):
            with self.subTest(what=what), mock.patch.object(childenv, "check_env", wraps=childenv.check_env) as builder:
                rc, tail = Shell(host).run([sys.executable, "-c", self.probe], what=what,
                                          env={"HOME": str(self.owner), "SSH_AUTH_SOCK": "/declared-agent",
                                               "GIT_SSH_COMMAND": "declared-ssh"})
                self.assertEqual(rc, 0, tail)
                self.assert_isolated()
                seen = json.loads(self.output.read_text())
                self.assertEqual(seen["home"], builder.call_args.kwargs["home"])
                self.assertEqual(seen["env"]["UV_CACHE_DIR"], str(self.owner / ".cache/uv"))
                self.assertEqual(seen["env"]["DOTNET_CLI_HOME"], str(self.owner))

    def test_cli_gate_in_real_git_checkout_cannot_find_owner_state_through_home(self):
        repo = self.root / "repo"
        repo.mkdir()
        checks = [{"id": "probe", "argv": [sys.executable, "-c", self.probe], "run": "gate",
                   "env": {"HOME": str(self.owner), "GH_TOKEN": "synthetic-token"}}]
        (repo / ".task-loop.json").write_text(json.dumps({"engine": {"base": "main", "checks": checks}}))
        for args in (("init", "-q", "-b", "main"), ("add", ".task-loop.json"), ("commit", "-qm", "canary")):
            subprocess.run(["git", "-c", "user.name=Canary", "-c", "user.email=canary@example.invalid", *args],
                           cwd=repo, capture_output=True, check=True)
        ran = tl_main("check", "--repo", str(repo), "--all", "probe", cwd=repo,
                      env={"HOME": str(self.owner), "XDG_CONFIG_HOME": str(self.root / "config"),
                           "SSH_AUTH_SOCK": "/synthetic-agent", "GIT_SSH_COMMAND": "synthetic-ssh"})
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assert_isolated()
