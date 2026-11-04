"""The migrated pool write uses real git with the engine's checkout and index pinning intact."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401

# isort: split
from git_porcelain import real_env

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env, snapshot
from taskloop.contracts.slots import SlotGitError


class RealGitPoolTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.repo = self.home / "repo"
        self.repo.mkdir()
        self.run_git(self.repo, "init", "-q", "-b", "main")
        self.run_git(self.repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                     "-c", "commit.gpgSign=false", "commit", "-qm", "initial", "--allow-empty")
        self.git = RealGit(snapshot())

    def run_git(self, path, *args):
        return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()

    def test_add_worktree_is_detached_at_the_requested_revision(self):
        slot = self.home / "slot"
        self.git.add_worktree(str(self.repo), str(slot), "main")
        self.assertEqual(self.run_git(slot, "rev-parse", "HEAD"), self.run_git(self.repo, "rev-parse", "main"))
        self.assertEqual(self.run_git(slot, "rev-parse", "--abbrev-ref", "HEAD"), "HEAD")

    def test_add_worktree_preserves_failures_without_creating_a_checkout(self):
        slot = self.home / "slot"
        with self.assertRaises(SlotGitError):
            self.git.add_worktree(str(self.repo), str(slot), "missing-revision")
        self.assertFalse(slot.exists())

    def test_add_from_a_linked_checkout_keeps_the_environment_pinned(self):
        first = self.home / "first"
        self.git.add_worktree(str(self.repo), str(first), "main")
        gitdir = Path(self.run_git(first, "rev-parse", "--absolute-git-dir"))
        decoy = self.home / "decoy"
        decoy.mkdir()
        self.run_git(self.repo, "config", "core.worktree", str(decoy))
        polluted = {**snapshot().vars, "GIT_DIR": str(decoy), "GIT_WORK_TREE": str(decoy), "GIT_INDEX_FILE": str(decoy / "index")}
        port = RealGit(Env(polluted))
        slot = self.home / "slot"
        index_before = (gitdir / "index").read_bytes()
        env_before = port.git_env(first)
        with (mock.patch("git_porcelain.real.real_env.pinned", wraps=real_env.pinned) as pin,
              mock.patch("git_porcelain.real.subprocess.run", wraps=subprocess.run) as run):
            port.add_worktree(str(first), str(slot), "main")
        pin.assert_called_once_with(first)
        child = run.call_args.kwargs["env"]
        self.assertEqual(child["GIT_DIR"], str(gitdir))
        self.assertEqual(child["GIT_WORK_TREE"], str(first))
        self.assertNotIn("GIT_INDEX_FILE", child)
        self.assertTrue((slot / ".git").is_file())
        self.assertFalse((decoy / "index").exists())
        self.assertEqual((gitdir / "index").read_bytes(), index_before)
        self.assertEqual(port.git_env(first), env_before)
        self.assertEqual(port.env.vars, polluted)
