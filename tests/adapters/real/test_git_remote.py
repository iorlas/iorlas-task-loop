"""The port's remote calls against a bare origin: what moved on the remote, and what the caller is told when it did not."""

from pathlib import Path
from unittest import mock

import pytest
import support.paths  # noqa: F401
from git_porcelain.real import Done, RealRepo

from taskloop.adapters import git_ops
from taskloop.adapters.git import RealGit
from tlkernel.env import Env, snapshot
from tlkernel.landmatchers import Push
from tlkernel.slots import GitReadFailure, RefRace, SlotGitError
from tltestkit.case import Case
from tltestkit.checked import run_checked
from tltestkit.tmpdir import TemporaryDirectory


class RealGitRemoteTest(Case):
    def setup_method(self):
        temporary = TemporaryDirectory()
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
        return run_checked(["git", "-C", str(cwd or self.repo), *args], None, env=self.env, text=True).stdout.strip()

    def commit(self, message):
        self.run_git("commit", "--allow-empty", "-qm", message)
        return self.run_git("rev-parse", "HEAD")

    def hook(self, name, text, remote=False):
        folder = self.origin / "hooks" if remote else self.hooks
        path = folder / name
        path.write_text("#!/bin/sh\n" + text)
        path.chmod(0o755)

    def remote(self, ref="refs/heads/main"):
        return self.run_git("rev-parse", "--verify", "-q", ref, cwd=self.origin)

    def test_push_moves_the_remote_ref_and_a_moved_base_is_refused_in_the_words_callers_match(self):
        directory = str(self.repo)
        self.git.push(directory, "origin", f"{self.base}:refs/heads/main")
        assert self.remote() == self.base
        moved = self.commit("moved remote")
        self.git.push(directory, "origin", f"{moved}:refs/heads/main")
        with pytest.raises(SlotGitError) as caught:
            self.git.push(directory, "origin", f"{self.base}:refs/heads/main")
        assert Push.rejected(caught.value.output)
        assert self.remote() == moved

    def test_tag_and_delete_refspecs_reach_the_remote(self):
        directory = str(self.repo)
        self.git.push(directory, "origin", f"{self.base}:refs/heads/topic")
        self.run_git("tag", "v1")
        self.git.push(directory, "origin", "refs/tags/v1")
        assert self.remote("refs/tags/v1") == self.base
        with pytest.raises(SlotGitError):
            self.git.push(directory, "origin", ":refs/heads/topic")
        self.git.delete_remote_at(directory, "origin", "refs/heads/topic", self.base)
        assert self.git.ls_remote(directory, "origin", "refs/heads/topic") == []

    def test_pre_push_hook_refusal_keeps_output_and_is_not_retryable(self):
        self.hook("pre-push", "echo 'gate: rejected by policy; fetch first will not help' >&2\nexit 1\n")
        with pytest.raises(SlotGitError) as caught:
            self.git.push(str(self.repo), "origin", f"{self.base}:refs/heads/main")
        assert "gate: rejected by policy" in caught.value.output
        assert "gate: rejected by policy" in caught.value.tail
        assert not Push.rejected(caught.value.output)
        assert self.git.ls_remote(str(self.repo), "origin", "refs/heads/main") == []

    def test_remote_hook_refusal_is_not_a_moved_base(self):
        self.hook("pre-receive", "echo 'policy rejected; fetch first will not help' >&2\nexit 1\n", remote=True)
        with pytest.raises(SlotGitError) as caught:
            self.git.push(str(self.repo), "origin", f"{self.base}:refs/heads/main")
        assert "[remote rejected]" in caught.value.output
        assert "pre-receive hook declined" in caught.value.tail
        assert not Push.rejected(caught.value.output)

    def test_push_lease_moves_the_ref_while_last_fetched_and_refuses_a_stale_lease(self):
        directory = str(self.repo)
        self.git.push(directory, "origin", f"{self.base}:refs/heads/topic")
        self.git.fetch(directory)
        mine = self.commit("mine")
        outcome = self.git.push_lease(directory, "origin", "HEAD:refs/heads/topic", self.base)
        assert outcome.ok
        assert self.remote("refs/heads/topic") == mine
        self.run_git("update-ref", "refs/remotes/origin/topic", self.base)
        self.commit("local work the lease would overwrite")
        stale = self.git.push_lease(directory, "origin", "HEAD:refs/heads/topic", self.base)
        assert not stale.ok
        assert "stale info" in stale.output
        assert Push.rejected(stale.output)
        assert self.remote("refs/heads/topic") == mine

    def test_push_lease_ends_a_push_that_outlives_its_wall_with_words(self):
        self.hook("pre-push", "exec sleep 30\n")
        with mock.patch.object(git_ops, "PUSH_WALL_S", 0.5):
            outcome = self.git.push_lease(str(self.repo), "origin", "HEAD:refs/heads/topic", "")
        assert not outcome.ok
        assert "timed out" in outcome.output
        assert self.git.ls_remote(str(self.repo), "origin", "refs/heads/topic") == []

    def test_guarded_delete_keeps_a_moved_ref_and_is_done_when_the_ref_is_gone(self):
        directory = str(self.repo)
        self.git.push(directory, "origin", f"{self.base}:refs/heads/topic")
        moved = self.commit("moved")
        self.git.push(directory, "origin", f"{moved}:refs/heads/topic")
        with pytest.raises(SlotGitError):
            self.git.delete_remote_at(directory, "origin", "refs/heads/topic", self.base)
        assert self.remote("refs/heads/topic") == moved
        self.git.delete_remote_at(directory, "origin", "refs/heads/topic", moved)
        self.git.delete_remote_at(directory, "origin", "refs/heads/topic", moved)
        assert self.git.ls_remote(directory, "origin", "refs/heads/topic") == []

    def test_delete_that_cannot_ask_the_remote_whether_the_ref_is_gone_is_a_fault(self):
        self.run_git("remote", "set-url", "origin", str(self.root / "missing.git"))
        with pytest.raises(GitReadFailure):
            self.git.delete_remote_at(str(self.repo), "origin", "refs/heads/topic", self.base)

    def test_fetch_brings_the_remote_in_and_a_missing_remote_is_the_ports_error_with_git_words(self):
        directory = str(self.repo)
        self.git.push(directory, "origin", f"{self.base}:refs/heads/topic")
        self.git.fetch(directory)
        assert self.run_git("rev-parse", "refs/remotes/origin/topic") == self.base
        self.run_git("remote", "set-url", "origin", str(self.root / "missing.git"))
        with pytest.raises(SlotGitError, match="fatal:") as caught:
            self.git.fetch(directory)
        assert "missing.git" in caught.value.output

    def lose_ref_locks(self, losses):
        """git loses `losses` fetches to a concurrent fetch's ref lock (a real lock race cannot be timed), then runs as itself."""
        real, left = RealRepo.run, [losses]

        def run(repo, cwd, *args, **kw):
            if args[:1] == ("fetch",) and left[0] > 0:
                left[0] -= 1
                return Done(1, b"", "error: cannot lock ref 'refs/remotes/origin/main': is at X but expected Y")
            return real(repo, cwd, *args, **kw)
        return mock.patch.object(RealRepo, "run", run)

    def test_fetch_waits_out_a_ref_lock_with_the_injected_sleep_and_gives_up_after_five_tries(self):
        directory = str(self.repo)
        self.git.push(directory, "origin", f"{self.base}:refs/heads/main")
        self.run_git("update-ref", "refs/heads/topic", self.base, cwd=self.origin)
        sleeps = []
        self.git = RealGit(Env(self.env), sleeps.append, pinned=False)
        with self.lose_ref_locks(5), pytest.raises(RefRace):
            self.git.fetch(directory)
        assert sleeps == pytest.approx([0.1, 0.2, 0.3, 0.4])
        sleeps.clear()
        with self.lose_ref_locks(1):
            self.git.fetch(directory)
        assert sleeps == [0.1]
        assert self.run_git("rev-parse", "refs/remotes/origin/topic") == self.base

    def test_fetch_ref_brings_one_ref_to_fetch_head_and_a_refusal_is_not_absence(self):
        self.git.push(str(self.repo), "origin", f"{self.base}:refs/heads/topic")
        self.git.fetch_ref(str(self.repo), str(self.origin), "topic")
        assert self.run_git("rev-parse", "FETCH_HEAD") == self.base
        with pytest.raises(SlotGitError) as caught:
            self.git.fetch_ref(str(self.repo), str(self.origin), "absent")
        assert "absent" in caught.value.output
