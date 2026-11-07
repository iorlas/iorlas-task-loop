"""Checks never inherit transport credentials, even through their declared environment."""
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.argv_checks import ArgvChecks

from taskloop.adapters.git import RealGit
from taskloop.adapters.procs import Ran
from tlkernel.checksport import CheckSpec
from tlkernel.childenv import check_env
from tlkernel.env import Env


class CheckEnvironment(Case):
    def test_check_runner_scrubs_parent_transport_credentials(self):
        base = {"HOME": "/owner", "SSH_AUTH_SOCK": "/agent", "GH_TOKEN": "secret", "GIT_SSH_COMMAND": "ssh custom"}
        with mock.patch("support.argv_checks.run_group", return_value=Ran(0, "", "", 0, False)) as runner:
            ArgvChecks(Env(base)).run(CheckSpec(argv=["true"], cwd="/repo"))
        env = runner.call_args.args[2]
        assert not {"SSH_AUTH_SOCK", "GH_TOKEN", "GIT_SSH_COMMAND"} & env.keys()
        assert env["HOME"] == "/owner"
        git_env = RealGit(Env(base)).git_env("/repo")
        assert git_env["SSH_AUTH_SOCK"] == "/agent"
        assert git_env["GIT_SSH_COMMAND"] == "ssh custom"

    def test_declared_environment_cannot_restore_credentials(self):
        secrets = dict.fromkeys(("SSH_AUTH_SOCK", "GIT_SSH_COMMAND", "GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR",
                                 "GIT_ASKPASS", "SSH_ASKPASS", "GIT_CREDENTIAL_HELPER", "GIT_CREDENTIAL"), "secret")
        env = check_env(secrets, {**secrets, "MODE": "safe"}, home="/scratch")
        assert not secrets.keys() & env.keys()
        assert env["MODE"] == "safe"
