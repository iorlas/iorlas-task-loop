"""A suite child can push to its own origin while tl's refusing global hook is installed."""
import os
import subprocess
from pathlib import Path

from support.argv_checks import ArgvChecks
from support.case import Case
from support.checked import run_checked
from support.tmpdir import TemporaryDirectory

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env
from taskloop.contracts.ports import CheckSpec


class CheckHooks(Case):
    def test_suite_push_uses_git_defaults_instead_of_the_pinned_judge(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, origin = root / "repo", root / "origin.git"
            repo.mkdir()
            base = {"PATH": os.environ["PATH"], "HOME": str(root), "XDG_CONFIG_HOME": str(root / "config"),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_AUTHOR_NAME": "Suite", "GIT_AUTHOR_EMAIL": "suite@example.invalid",
                    "GIT_COMMITTER_NAME": "Suite", "GIT_COMMITTER_EMAIL": "suite@example.invalid"}
            port = RealGit(Env(base))
            pinned = port.git_env(repo)
            hooks = Path(pinned[f"GIT_CONFIG_VALUE_{int(pinned['GIT_CONFIG_COUNT']) - 1}"])
            hooks.mkdir(parents=True)
            hook = hooks / "pre-push"
            hook.write_text("#!/bin/sh\necho 'no suite receipt for this tree and base' >&2\nexit 1\n")
            hook.chmod(0o755)
            for args in (("init", "--bare", str(origin)), ("init", "-b", "main"),
                         ("commit", "--allow-empty", "-m", "suite fixture"), ("remote", "add", "origin", str(origin))):
                run_checked(["git", *args], repo, env=base)
            refused = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=repo, env=pinned,
                                     capture_output=True, text=True, check=False)
            assert refused.returncode != 0
            assert "no suite receipt" in refused.stderr
            result = ArgvChecks(Env(pinned)).run(CheckSpec(argv=["git", "push", "origin", "HEAD:main"], cwd=str(repo)))
            assert result.exit == 0, result.out
            tip = run_checked(["git", "--git-dir", str(origin), "rev-parse", "refs/heads/main"], None, env=base, text=True).stdout.strip()
            assert tip == port.rev_parse(str(repo), "HEAD")
