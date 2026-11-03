"""Checks never inherit transport credentials, even through their declared environment."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.checks_argv import ArgvChecks
from taskloop.adapters.childenv import check_env
from taskloop.adapters.git import RealGit
from taskloop.adapters.procs import Ran
from taskloop.contracts.env import Env
from taskloop.contracts.ports import CheckSpec


class CheckEnvironment(unittest.TestCase):
    def test_check_runner_scrubs_parent_transport_credentials(self):
        base = {"HOME": "/owner", "SSH_AUTH_SOCK": "/agent", "GH_TOKEN": "secret", "GIT_SSH_COMMAND": "ssh custom"}
        with mock.patch("taskloop.adapters.checks_argv.run_group", return_value=Ran(0, "", "", 0, False)) as runner:
            ArgvChecks(Env(base)).run(CheckSpec(argv=["true"], cwd="/repo"))
        env = runner.call_args.args[2]
        self.assertFalse({"SSH_AUTH_SOCK", "GH_TOKEN", "GIT_SSH_COMMAND"} & env.keys())
        self.assertNotEqual(env["HOME"], "/owner")
        self.assertFalse(Path(env["HOME"]).exists())
        git_env = RealGit(Env(base)).git_env("/repo")
        self.assertEqual(git_env["SSH_AUTH_SOCK"], "/agent")
        self.assertEqual(git_env["GIT_SSH_COMMAND"], "ssh custom")

    def test_declared_environment_cannot_restore_credentials(self):
        secrets = dict.fromkeys(("SSH_AUTH_SOCK", "GIT_SSH_COMMAND", "GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR",
                                 "GIT_ASKPASS", "SSH_ASKPASS", "GIT_CREDENTIAL_HELPER", "GIT_CREDENTIAL"), "secret")
        env = check_env(secrets, {**secrets, "MODE": "safe"}, home="/scratch")
        self.assertFalse(secrets.keys() & env.keys())
        self.assertEqual(env["MODE"], "safe")
