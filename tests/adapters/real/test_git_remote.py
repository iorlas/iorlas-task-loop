"""Remote transport against a bare origin, including refusal and observation semantics."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401

from taskloop.adapters import procs
from taskloop.adapters.git import RealGit
from taskloop.adapters.git_ops import PUSH_WALL_S
from taskloop.contracts.env import Env, snapshot
from taskloop.contracts.slots import SlotGitError
from taskloop.domain.land.matchers import Push


class RealGitRemoteTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo, self.origin = self.root / "repo", self.root / "origin.git"
        self.repo.mkdir()
        self.env = {**snapshot().vars, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
        self.git = RealGit(Env(self.env), pinned=False)
        self.run_git("init", "-q", "--bare", "-b", "main", str(self.origin))
        self.run_git("init", "-q", "-b", "main")
        self.run_git("config", "commit.gpgSign", "false")
        self.hooks = self.root / "hooks"
        self.hooks.mkdir()
        self.run_git("config", "core.hooksPath", str(self.hooks))
        self.run_git("remote", "add", "origin", str(self.origin))
        self.base = self.commit("initial")

    def run_git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], env=self.env,
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.run_git("commit", "--allow-empty", "-qm", message)
        return self.run_git("rev-parse", "HEAD")

    def hook(self, name, text, remote=False):
        folder = self.origin / "hooks" if remote else self.hooks
        path = folder / name
        path.write_text("#!/bin/sh\n" + text)
        path.chmod(0o755)

    def test_push_success_and_moved_base_refusal(self):
        directory = str(self.repo)
        with mock.patch("taskloop.adapters.git_base.procs.run", wraps=procs.run) as run:
            self.git.push(directory, "origin", f"{self.base}:refs/heads/main")
        self.assertEqual(run.call_count, 1)
        moved = self.commit("moved remote")
        self.git.push(directory, "origin", f"{moved}:refs/heads/main")
        with self.assertRaises(SlotGitError) as caught:
            self.git.push(directory, "origin", f"{self.base}:refs/heads/main")
        self.assertTrue(Push.rejected(caught.exception.output))
        self.assertEqual(self.run_git("rev-parse", "main", cwd=self.origin), moved)

    def test_pre_push_hook_refusal_keeps_output_and_is_not_retryable(self):
        self.hook("pre-push", "echo 'gate: rejected by policy; fetch first will not help' >&2\nexit 1\n")
        with self.assertRaises(SlotGitError) as caught:
            self.git.push(str(self.repo), "origin", f"{self.base}:refs/heads/main")
        self.assertIn("gate: rejected by policy", caught.exception.output)
        self.assertIn("gate: rejected by policy", caught.exception.tail)
        self.assertFalse(Push.rejected(caught.exception.output))
        self.assertEqual(self.git.ls_remote(str(self.repo), "origin", "refs/heads/main"), [])

    def test_remote_hook_refusal_is_not_a_moved_base(self):
        self.hook("pre-receive", "echo 'policy rejected; fetch first will not help' >&2\nexit 1\n", remote=True)
        with self.assertRaises(SlotGitError) as caught:
            self.git.push(str(self.repo), "origin", f"{self.base}:refs/heads/main")
        self.assertIn("[remote rejected]", caught.exception.output)
        self.assertFalse(Push.rejected(caught.exception.output))

    def test_stale_lease_and_guarded_delete_preserve_the_moved_remote(self):
        directory = str(self.repo)
        self.git.push(directory, "origin", f"{self.base}:refs/heads/topic")
        moved = self.commit("moved")
        self.git.push(directory, "origin", f"{moved}:refs/heads/topic")
        self.run_git("update-ref", "refs/remotes/origin/topic", self.base)
        self.commit("local work the lease would overwrite")
        outcome = self.git.push_lease(directory, "origin", "HEAD:refs/heads/topic")
        self.assertFalse(outcome.ok)
        self.assertIn("stale info", outcome.output)
        with self.assertRaises(SlotGitError):
            self.git.delete_remote_at(directory, "origin", "refs/heads/topic", self.base)
        self.assertEqual(self.run_git("rev-parse", "topic", cwd=self.origin), moved)
        self.git.delete_remote_at(directory, "origin", "refs/heads/topic", moved)
        self.git.delete_remote_at(directory, "origin", "refs/heads/topic", moved)
        self.assertEqual(self.git.ls_remote(directory, "origin", "refs/heads/topic"), [])

    def test_scoped_fetch_writes_fetch_head_and_refusal_is_not_absence(self):
        self.git.push(str(self.repo), "origin", f"{self.base}:refs/heads/topic")
        self.git.fetch_ref(str(self.repo), str(self.origin), "topic")
        self.assertEqual(self.run_git("rev-parse", "FETCH_HEAD"), self.base)
        with self.assertRaises(SlotGitError):
            self.git.fetch_ref(str(self.repo), str(self.origin), "absent")

    def test_lfs_timeout_words_survive_without_an_installed_lfs_binary(self):
        with mock.patch.object(self.git, "_run", side_effect=subprocess.TimeoutExpired("git", PUSH_WALL_S)):
            outcome = self.git.lfs_push(str(self.repo), "origin", [self.base])
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.output, "git lfs timed out after 60 min")
