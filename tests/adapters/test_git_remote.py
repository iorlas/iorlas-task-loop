"""Stage 5 remote operations preserve retries, read failures, and command transcripts."""

import subprocess
from unittest import mock

import support.paths  # noqa: F401

# isort: split

import pytest
from support.case import Case

from taskloop.adapters.git import RealGit
from taskloop.adapters.git_ops import PUSH_WALL_S
from taskloop.contracts.env import Env
from taskloop.contracts.slots import GitReadFailure, RefRace, SlotGitError


class GitRemoteTest(Case):
    def setup_method(self):
        self.sleep = mock.Mock()
        self.git = RealGit(Env(), self.sleep, pinned=False)

    def test_fetch_stays_unbounded_and_scoped_fetch_has_no_destination(self):
        with (mock.patch.object(self.git, "_pool") as pool,
              mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run):
            self.git.fetch("/pool")
            run.assert_called_once_with("/pool", "fetch", "-q", "origin")
            run.reset_mock()
            self.git.fetch_ref("/pool", "/source", "topic")
            run.assert_called_once_with("/pool", "fetch", "-q", "/source", "topic", extra=None)
            pool.assert_not_called()

    def test_fetch_retries_exactly_five_ref_locks_using_the_injected_sleep(self):
        failed = subprocess.CompletedProcess([], 1, "", "error: cannot lock ref 'refs/remotes/origin/main'")
        with mock.patch.object(self.git, "_run", return_value=failed) as run, pytest.raises(RefRace):
            self.git.fetch("/pool")
        assert run.call_count == 5
        assert self.sleep.call_args_list == [mock.call(0.1 * i) for i in range(1, 5)]
        run.assert_called_with("/pool", "fetch", "-q", "origin")

    def test_fetch_stops_after_success_or_a_transport_failure(self):
        race = subprocess.CompletedProcess([], 1, "", "error: cannot lock ref 'origin/main'")
        with mock.patch.object(self.git, "_run", side_effect=[race, subprocess.CompletedProcess([], 0, "", "")]) as run:
            self.git.fetch("/pool")
            assert run.call_count == 2
        failed = subprocess.CompletedProcess([], 128, "", "fatal: transport unavailable")
        with mock.patch.object(self.git, "_run", return_value=failed) as run:
            with pytest.raises(SlotGitError, match="fatal: transport unavailable"):
                self.git.fetch("/pool")
            run.assert_called_once()

    def test_long_fetch_transport_failures_keep_the_first_diagnostic(self):
        text = "fatal: unable to access origin: Could not resolve host\n" + "progress\n" * 500
        with mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 128, "", text)):
            for name, args in (("fetch", ()), ("fetch_ref", ("/source", "topic"))):
                with self.subTest(operation=name), pytest.raises(SlotGitError) as caught:
                    getattr(self.git, name)("/pool", *args)
                assert caught.value.tail == text.splitlines()[0]
                if name == "fetch_ref":
                    assert caught.value.output == text

    def test_uploads_keep_complete_output_and_one_process(self):
        transcript = "  upload progress\n" * 500 + "hook: details\n\n"
        for name, args in (("push_lease", ("HEAD:topic",)), ("lfs_push", (["HEAD", "topic"],))):
            with (self.subTest(operation=name), mock.patch.object(self.git, "_pool") as pool,
                  mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 1, transcript, "")) as run):
                result = getattr(self.git, name)("/pool", "origin", *args)
                assert not result.ok
                assert result.output == transcript
                run.assert_called_once()
                assert run.call_args.kwargs["timeout"] == PUSH_WALL_S
                pool.assert_not_called()

    def test_successful_uploads_keep_hook_and_progress_output_too(self):
        text = "  hook progress\n\n"
        for name, args in (("push_lease", ("HEAD:topic",)), ("lfs_push", (["HEAD"],))):
            with (self.subTest(operation=name),
                  mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 0, text, "success\n"))):
                result = getattr(self.git, name)("/pool", "origin", *args)
            assert result.ok
            assert result.output == text + "success\n"

    def test_push_and_lfs_timeouts_retain_the_port_words(self):
        for name, args, command in (("push_lease", ("HEAD:topic",), "push"), ("lfs_push", (["HEAD"],), "lfs")):
            with (self.subTest(operation=name),
                  mock.patch.object(self.git, "_run", side_effect=subprocess.TimeoutExpired("git", PUSH_WALL_S))):
                result = getattr(self.git, name)("/pool", "origin", *args)
                assert not result.ok
                assert result.output == f"git {command} timed out after 60 min"

    def test_remote_delete_verifies_absence_but_never_swallows_a_failed_query(self):
        refused = subprocess.CompletedProcess([], 1, "", "! [rejected] topic (stale info)\n")
        with mock.patch.object(self.git, "_run", return_value=refused), mock.patch.object(self.git, "ls_remote") as query:
            query.return_value = []
            self.git.delete_remote_at("/pool", "origin", "refs/heads/topic", "old")
            query.return_value = [object()]
            with pytest.raises(SlotGitError):
                self.git.delete_remote_at("/pool", "origin", "refs/heads/topic", "old")
            query.side_effect = GitReadFailure("unavailable")
            with pytest.raises(GitReadFailure):
                self.git.delete_remote_at("/pool", "origin", "refs/heads/topic", "old")
