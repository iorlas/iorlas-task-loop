"""Ordinary Git transport never injects the retired checked-push marker."""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from support.case import Case

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env, snapshot
from taskloop.contracts.slots import SlotGitError


def sh(*a, cwd, check=True):
    env = {k: v for k, v in os.environ.items() if k != "TL_LAND"}
    return subprocess.run(list(a), cwd=str(cwd), check=check, capture_output=True, text=True, env=env)


class PortPushHasNoGateAuthority(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        root = Path(os.path.realpath(self.tmp.name))
        self.remote, self.repo, hooks = root / "o.git", root / "r", root / "hooks"
        sh("git", "init", "-q", "--bare", "-b", "main", str(self.remote), cwd=root)
        self.repo.mkdir()
        setup = (
            ["init", "-q", "-b", "main"],
            ["config", "user.email", "a@b"],
            ["config", "user.name", "n"],
            ["config", "core.hooksPath", str(hooks)],
        )
        for a in setup:
            sh("git", *a, cwd=self.repo)
        (self.repo / "f").write_text("1")
        sh("git", "add", "f", cwd=self.repo)
        sh("git", "commit", "-q", "-m", "one", cwd=self.repo)
        sh("git", "remote", "add", "origin", str(self.remote), cwd=self.repo)
        hooks.mkdir()
        hook = hooks / "pre-push"
        hook.write_text('#!/bin/sh\n[ -n "$TL_LAND" ] || { echo refused: not green >&2; exit 1; }\n')
        hook.chmod(0o755)
        bare = {"PATH": os.environ.get("PATH", "")}
        ran = subprocess.run([str(hook)], capture_output=True, text=True, env=bare, check=False)
        why = ran.stderr.strip() or "no output"
        assert ran.returncode == 1, (f"precondition: the refusing pre-push hook cannot run here ({why}): "
                         f"is {hooks} on a noexec mount, or is /bin/sh missing?")
        self.port = RealGit(Env({k: v for k, v in snapshot().vars.items() if k != "TL_LAND"}), pinned=False)

    def test_the_port_and_plain_push_both_meet_the_refusing_hook(self):
        plain = sh("git", "push", "-q", "origin", "main", cwd=self.repo, check=False)
        assert plain.returncode != 0, ("precondition: this git ignored core.hooksPath, so the refusing hook never ran "
                            f"({sh('git', '--version', cwd=self.repo).stdout.strip()}; push said: {plain.stderr.strip()!r})")
        with pytest.raises(SlotGitError):
            self.port.push(str(self.repo), "origin", "main")
        assert sh("git", "rev-parse", "--verify", "main", cwd=self.remote, check=False).returncode != 0

    def test_the_port_remote_delete_meets_the_refusing_hook(self):
        git = self.port
        sh("git", "push", "--no-verify", "origin", "main", cwd=self.repo)
        sh("git", "branch", "side", cwd=self.repo)
        sh("git", "push", "--no-verify", "origin", "side", cwd=self.repo)
        oid = sh("git", "rev-parse", "side", cwd=self.repo).stdout.strip()
        with pytest.raises(SlotGitError):
            git.delete_remote_at(str(self.repo), "origin", "refs/heads/side", oid)
        assert sh("git", "rev-parse", "side", cwd=self.remote).stdout.strip() == oid

    def test_the_port_lease_push_meets_the_refusing_hook(self):
        outcome = self.port.push_lease(str(self.repo), "origin", "HEAD:refs/heads/main", "")
        assert not outcome.ok
        assert "refused: not green" in outcome.output
        assert sh("git", "rev-parse", "--verify", "main", cwd=self.remote, check=False).returncode != 0
