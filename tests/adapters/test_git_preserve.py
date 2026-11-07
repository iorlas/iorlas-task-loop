"""Preservation operations keep the Git port's semantics across the porcelain seam."""
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401

# isort: split
import pytest
from git_porcelain import errors
from git_porcelain.api import BranchHeld, NothingToRecord, Recorded, Sha, WorktreeInfo
from git_porcelain.testing import FakeRepo
from support.case import Case

from taskloop.adapters.git import RealGit
from tlkernel.env import Env
from tlkernel.slots import BranchPinned, DirtyTree, GitReadFailure, IndexLocked, RefRace, SlotGitError


class GitPreserveTest(Case):
    def setup_method(self):
        self.git = RealGit(Env())

    def test_record_preserves_the_current_branch_and_all_work(self):
        repo = FakeRepo.init(Path("/pool"))
        wt = repo.worktree(repo.path)
        wt.write_file("tracked", "one\n")
        wt.record("initial", paths="all")
        wt.write_file("tracked", "two\n")
        wt.write_file("untracked", "new\n")
        with (mock.patch.object(self.git, "_pool", return_value=repo),
              mock.patch.object(self.git, "branch", return_value="main"),
              mock.patch.object(self.git, "_must") as old):
            self.git.commit_all("/pool", "unused", "checkpoint")
        old.assert_not_called()
        assert not wt.dirty().raw
        assert wt.snapshot("main").branch == "main"
        tree = repo.tree("HEAD")
        assert tree is not None
        assert tree.read("untracked") == b"new\n"

    def test_detached_record_still_requires_exclusive_branch_creation(self):
        with (mock.patch.object(self.git, "branch", return_value=""),
              mock.patch.object(self.git, "checkout_new") as create,
              mock.patch.object(self.git, "_pool") as make):
            record = make.return_value.worktree.return_value.record
            record.return_value = Recorded(Sha("checkpoint"))
            self.git.commit_all("/pool", "wip/slot", "checkpoint")
        create.assert_called_once_with("/pool", "wip/slot", "HEAD")
        record.assert_called_once_with("checkpoint", paths="all", hooks=False)

    def test_empty_record_remains_a_port_failure(self):
        with (mock.patch.object(self.git, "branch", return_value="main"),
              mock.patch.object(self.git, "_pool") as make):
            make.return_value.worktree.return_value.record.return_value = NothingToRecord()
            with pytest.raises(SlotGitError, match="nothing to commit"):
                self.git.commit_all("/pool", "unused", "empty")

    def test_park_detaches_without_cleaning_and_leaves_the_branch_tip(self):
        repo = FakeRepo.init(Path("/pool"))
        wt = repo.worktree(repo.path)
        wt.write_file("tracked", "one\n")
        wt.record("initial", paths="all")
        before = repo.branches()
        wt.write_file("keep", "untracked\n")
        with mock.patch.object(self.git, "_pool", return_value=repo):
            assert self.git.checkout_detached("/pool", "main") is None
        assert wt.snapshot("main").branch is None
        assert repo.branches() == before
        assert "keep" in wt.dirty().untracked

    def test_restart_uses_non_forced_branch_replacement_without_cleanup(self):
        with mock.patch.object(self.git, "_pool") as make:
            assert self.git.checkout_reset("/pool", "task/a", "origin/main") is None
        make.return_value.worktree.assert_called_once_with(Path("/pool"))
        make.return_value.worktree.return_value.take_branch.assert_called_once_with("task/a", "origin/main", mode="restart")

    def test_restart_preserves_the_branch_holder(self):
        holder = WorktreeInfo(Path("/other"), Sha("tip"), "task/a", False, None)
        with mock.patch.object(self.git, "_pool") as make:
            make.return_value.worktree.return_value.take_branch.return_value = BranchHeld((holder,))
            with pytest.raises(BranchPinned) as caught:
                self.git.checkout_reset("/pool", "task/a", "origin/main")
        assert caught.value.where == "/other"

    def test_write_failures_keep_the_port_error_family(self):
        cases = ((errors.IndexLocked("locked"), IndexLocked),
                 (errors.RefRace("raced"), RefRace),
                 (errors.BranchPinned("held", "/holder"), BranchPinned),
                 (errors.GitUnavailable("local changes would be overwritten"), DirtyTree))
        for method, args, operation in (("commit_all", ("unused", "checkpoint"), "record"),
                                        ("checkout_detached", ("main",), "park"),
                                        ("checkout_reset", ("task/a", "main"), "take_branch")):
            for error, expected in cases:
                with (self.subTest(method=method, error=type(error).__name__),
                      mock.patch.object(self.git, "branch", return_value="main"),
                      mock.patch.object(self.git, "_pool") as make):
                    getattr(make.return_value.worktree.return_value, operation).side_effect = error
                    with pytest.raises(expected) as caught:
                        getattr(self.git, method)("/pool", *args)
                    assert caught.value.__cause__ is error

    def test_branch_lookup_requires_an_exact_name_and_propagates_read_failures(self):
        with mock.patch.object(self.git, "_pool") as make:
            make.return_value.branches.return_value = (("task/ab", Sha("tip")),)
            assert not self.git.has_branch("/pool", "task/a")
            assert self.git.has_branch("/pool", "task/ab")
            make.return_value.branches.return_value = ()
            assert not self.git.has_branch("/pool", "absent")
            make.return_value.branches.side_effect = errors.GitUnavailable("unreadable")
            with pytest.raises(GitReadFailure):
                self.git.has_branch("/pool", "task/a")
