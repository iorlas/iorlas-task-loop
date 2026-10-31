"""The port's own pushes (the release, a remote branch delete) carry TL_LAND, so tl's pre-push hook lets them through; a plain
`git push` meets the same refusing hook. Real git, a bare remote and a hook that refuses unless TL_LAND is set."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import snapshot


def sh(*a, cwd, check=True):
    env = {k: v for k, v in os.environ.items() if k != "TL_LAND"}  # a release run exports it: the plain push must not see it
    return subprocess.run(list(a), cwd=str(cwd), check=check, capture_output=True, text=True, env=env)


class PortPushCarriesLandMarker(unittest.TestCase):
    def setUp(self):
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

    def test_the_port_push_passes_the_hook_and_a_plain_push_does_not(self):
        self.assertNotEqual(sh("git", "push", "-q", "origin", "main", cwd=self.repo, check=False).returncode, 0)
        RealGit(snapshot()).push(str(self.repo), "origin", "main")
        self.assertEqual(sh("git", "rev-parse", "main", cwd=self.remote).stdout, sh("git", "rev-parse", "main", cwd=self.repo).stdout)

    def test_the_port_remote_delete_passes_the_hook(self):
        git = RealGit(snapshot())
        git.push(str(self.repo), "origin", "main")
        sh("git", "branch", "side", cwd=self.repo)
        git.push(str(self.repo), "origin", "side")
        oid = sh("git", "rev-parse", "side", cwd=self.repo).stdout.strip()
        git.delete_remote_at(str(self.repo), "origin", "refs/heads/side", oid)
        self.assertNotEqual(sh("git", "rev-parse", "--verify", "side", cwd=self.remote, check=False).returncode, 0)
