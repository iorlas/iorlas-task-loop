"""Worktree creation crosses the porcelain seam without changing the Git port's errors."""

import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401

# isort: split
from git_porcelain import errors
from git_porcelain.testing import FakeRepo

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env
from taskloop.contracts.slots import BranchPinned, DirtyTree, IndexLocked, MissingRevision, NotARepo, RefRace, SlotGitError


class GitPoolTest(unittest.TestCase):
    def setUp(self):
        self.git = RealGit(Env())

    def test_add_worktree_uses_the_porcelain_fake(self):
        repo = FakeRepo.init(Path("/pool"), config={"user.name": "Test", "user.email": "test@example.invalid"})
        work = repo.worktree(repo.path)
        work.write_file("tracked", "one\n")
        work.record("initial", paths="all")
        with mock.patch("taskloop.adapters.git.RealRepo", return_value=repo) as make:
            self.assertIsNone(self.git.add_worktree("/pool", "/slot", "main"))
        added = repo.worktree(Path("/slot")).snapshot("main")
        self.assertIsNone(added.branch)
        self.assertEqual(added.head, work.snapshot("main").head)
        self.assertFalse(make.call_args.kwargs["memoize"])
        self.assertEqual(make.call_args.args, (Path("/pool"),))

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
                with self.assertRaises(expected) as caught:
                    self.git.add_worktree("/pool", "/slot", "main")
                self.assertIs(caught.exception.__cause__, error)
                if isinstance(caught.exception, BranchPinned):
                    self.assertEqual(caught.exception.where, "/holder")

    def test_fake_missing_revision_is_a_slot_error_and_creates_nothing(self):
        repo = FakeRepo.init(Path("/pool"))
        with (mock.patch("taskloop.adapters.git.RealRepo", return_value=repo),
              self.assertRaises(SlotGitError)):
            self.git.add_worktree("/pool", "/slot", "absent")
        self.assertEqual([w.path for w in repo.worktrees()], [repo.path])

    def test_unpinned_add_keeps_the_unpinned_runner(self):
        self.git.pinned = False
        with mock.patch.object(self.git, "_must") as run, mock.patch("taskloop.adapters.git.RealRepo") as make:
            self.git.add_worktree("/pool", "/slot", "main")
        run.assert_called_once_with("/pool", "worktree", "add", "--detach", "/slot", "main")
        make.assert_not_called()
