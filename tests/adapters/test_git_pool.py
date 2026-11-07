"""Worktree pool operations cross the porcelain seam with the Git port's outcomes."""
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401

# isort: split
import pytest
from git_porcelain import errors
from git_porcelain.real import Done
from git_porcelain.testing import FakeRepo
from support.case import Case

from taskloop.adapters.git import RealGit
from tlkernel.env import Env
from tlkernel.slots import (
    BranchPinned,
    Checkout,
    DirtyTree,
    GitReadFailure,
    IndexLocked,
    MissingRevision,
    NotARepo,
    RefRace,
    SlotGitError,
)


class GitPoolTest(Case):
    def setup_method(self):
        self.git = RealGit(Env())

    def test_add_worktree_uses_the_porcelain_fake(self):
        repo = FakeRepo.init(Path("/pool"), config={"user.name": "Test", "user.email": "test@example.invalid"})
        work = repo.worktree(repo.path)
        work.write_file("tracked", "one\n")
        work.record("initial", paths="all")
        with mock.patch("taskloop.adapters.git.RealRepo", return_value=repo) as make:
            assert self.git.add_worktree("/pool", "/slot", "main") is None
        added = repo.worktree(Path("/slot")).snapshot("main")
        assert added.branch is None
        assert added.head == work.snapshot("main").head
        assert not make.call_args.kwargs["memoize"]
        assert make.call_args.args == (Path("/pool"),)

    def test_add_worktree_translates_each_porcelain_error(self):
        cases = (
            (errors.MissingRevision("missing"), MissingRevision),
            (errors.NotARepo("absent"), NotARepo),
            (errors.IndexLocked("locked"), IndexLocked),
            (errors.RefRace("raced"), RefRace),
            (errors.BranchPinned("held", "/holder"), BranchPinned),
            (errors.GitUnavailable("fatal: local changes would be overwritten"), DirtyTree),
            (errors.GitError("unknown"), SlotGitError),
        )
        for error, expected in cases:
            with (self.subTest(error=type(error).__name__),
                  mock.patch("taskloop.adapters.git.RealRepo") as make):
                make.return_value.add_worktree.side_effect = error
                with pytest.raises(expected) as caught:
                    self.git.add_worktree("/pool", "/slot", "main")
                assert caught.value.__cause__ is error
                if isinstance(caught.value, BranchPinned):
                    assert caught.value.where == "/holder"

    def test_fake_missing_revision_is_a_slot_error_and_creates_nothing(self):
        repo = FakeRepo.init(Path("/pool"))
        with (mock.patch("taskloop.adapters.git.RealRepo", return_value=repo),
              pytest.raises(SlotGitError)):
            self.git.add_worktree("/pool", "/slot", "absent")
        assert [w.path for w in repo.worktrees()] == [repo.path]

    def test_unpinned_pool_disables_porcelain_pinning(self):
        self.git.pinned = False
        with mock.patch("taskloop.adapters.git_pool.RealRepo.run") as run:
            self.git.add_worktree("/pool", "/slot", "main")
        assert not run.call_args.kwargs["pin"]

    def test_force_add_and_prune_delegate_without_memoization(self):
        with mock.patch("taskloop.adapters.git.RealRepo") as make:
            self.git.add_worktree_force("/pool", "/slot", "main")
            make.return_value.add_worktree.assert_called_once_with(Path("/slot"), "main", force=True)
            self.git.prune_worktrees("/pool")
            make.return_value.prune_worktrees.assert_called_once_with()
            assert not make.call_args.kwargs["memoize"]

    def test_removal_preserves_refusal_reason_and_never_prunes(self):
        with mock.patch("taskloop.adapters.git.RealRepo") as make:
            drop = make.return_value.drop_worktree
            assert self.git.remove_worktree("/pool", "/slot")
            assert self.git.remove_worktree_why("/pool", "/slot") == ""
            drop.assert_called_with(Path("/slot"), missing_ok=False)
            drop.side_effect = errors.WorktreeRemoveRefused("fatal: contains modified or untracked files")
            assert not self.git.remove_worktree("/pool", "/slot")
            assert self.git.remove_worktree_why("/pool", "/slot") == drop.side_effect.reason
            self.git.remove_worktree_force("/pool", "/slot")
            drop.assert_called_with(Path("/slot"), force=True, missing_ok=False)
            make.return_value.prune_worktrees.assert_not_called()

    def test_pool_read_failures_are_typed_and_state_failure_is_none(self):
        with mock.patch.object(self.git, "_pool") as make:
            repo = make.return_value
            repo.worktrees.side_effect = errors.GitUnavailable("unreadable")
            repo.worktree.return_value.dirty.side_effect = errors.GitUnavailable("unreadable")
            repo.worktree_state.side_effect = errors.GitUnavailable("unreadable")
            for read in (self.git.checkouts, self.git.dirty):
                with self.subTest(read=read.__name__), pytest.raises(GitReadFailure):
                    read("/pool")
            assert self.git.worktree_state("/pool") is None

    def test_listing_dirty_and_raw_state_keep_the_port_shapes(self):
        repo = FakeRepo.init(Path("/pool"))
        work = repo.worktree(repo.path)
        work.write_file("tracked", "one\n")
        work.record("initial", paths="all")
        with mock.patch("taskloop.adapters.git.RealRepo", return_value=repo):
            assert self.git.checkouts("/pool") == [Checkout(path="/pool", branch="main", main=True)]
            assert not self.git.dirty("/pool")
            work.write_file("tracked", "two\n")
            assert self.git.dirty("/pool")
            assert self.git.worktree_state("/pool") == repo.worktree_state(repo.path)

    def test_best_effort_operations_swallow_infrastructure_failures(self):
        with mock.patch("taskloop.adapters.git.RealRepo") as make:
            make.return_value.drop_worktree.side_effect = errors.GitUnavailable("unavailable")
            make.return_value.prune_worktrees.side_effect = errors.GitUnavailable("unavailable")
            assert not self.git.remove_worktree("/pool", "/slot")
            self.git.remove_worktree_force("/pool", "/slot")
            self.git.prune_worktrees("/pool")

    def test_listing_rejects_truncated_records_at_the_porcelain_boundary(self):
        with (mock.patch("git_porcelain.real.RealRepo.run", return_value=Done(0, b"worktree /checkout\0", "")),
              pytest.raises(GitReadFailure)):
            self.git.checkouts("/pool")

    def test_state_preserves_non_utf8_bytes(self):
        raw = b"# branch.head main\0? invalid-\xff\0"
        with mock.patch("git_porcelain.real.RealRepo.run", return_value=Done(0, raw, "")):
            assert self.git.worktree_state("/pool") == raw

    def test_tree_of_keeps_the_port_shape_over_a_porcelain_snapshot(self):
        repo = FakeRepo.init(Path("/pool"))
        work = repo.worktree(repo.path)
        work.write_file("tracked", "one\n")
        work.record("initial", paths="all")
        work.write_file("tracked", "two\n")
        work.write_file("untracked", "new\n")
        with mock.patch("taskloop.adapters.git.RealRepo", return_value=repo):
            tree = self.git.tree_of("/pool")
        assert isinstance(tree, str)
        assert tree == work.snapshot("HEAD").tree

    def test_tree_of_translates_snapshot_failure(self):
        with mock.patch.object(self.git, "_pool") as make:
            error = errors.GitUnavailable("snapshot unavailable")
            make.return_value.worktree.return_value.snapshot.side_effect = error
            with pytest.raises(SlotGitError) as caught:
                self.git.tree_of("/pool")
        assert caught.value.__cause__ is error
