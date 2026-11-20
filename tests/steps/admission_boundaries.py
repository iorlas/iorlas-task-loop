"""Admission audit: external ports reject a caller holding SQLite's write transaction.

AttemptAdmission prepares Git/profile/discussion input before committing claim intent;
claim and unclaim run outside its database-only _commit. ResumePlans.unchanged reads
stored evidence only. ChainAdmission._takeover, NextAdmission._advance and
ChecksAdmission._commit likewise recheck and record database facts without external IO.
The composition constructors pass these ports through without opening transactions.
Launcher commits dispatch intent before start and records entry registration separately;
test_launch probes the write lock on both sides of that registration callback.
Existing drain reconciliation observes unfinished claims and dispatches after restart.
No production effect was found inside these admission write transactions.
"""

import sqlite3
from collections.abc import Callable
from functools import wraps

import pytest
from doubles import PinnedViews
from git_porcelain.testing import FakeRepo, FakeWorktree

from taskloop.git_views import GitProfileFiles


def outside_transaction[**P, R](con: sqlite3.Connection, call: Callable[P, R]) -> Callable[P, R]:
    @wraps(call)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        assert not con.in_transaction, "external admission IO must run outside the write transaction"
        return call(*args, **kwargs)

    return guarded


def guard_git(con: sqlite3.Connection, patch: pytest.MonkeyPatch) -> None:
    """Guard opens and retained Git views, including profile and plan-reuse reads."""
    patch.setattr(PinnedViews, "__call__", outside_transaction(con, PinnedViews.__call__))
    patch.setattr(GitProfileFiles, "blob", outside_transaction(con, GitProfileFiles.blob))
    patch.setattr(FakeRepo, "identity", outside_transaction(con, FakeRepo.identity))
    patch.setattr(FakeRepo, "refs", outside_transaction(con, FakeRepo.refs))
    patch.setattr(FakeRepo, "tree", outside_transaction(con, FakeRepo.tree))
    patch.setattr(FakeRepo, "merge_base", outside_transaction(con, FakeRepo.merge_base))
    patch.setattr(FakeRepo, "is_ancestor", outside_transaction(con, FakeRepo.is_ancestor))
    patch.setattr(FakeRepo, "worktrees", outside_transaction(con, FakeRepo.worktrees))
    patch.setattr(FakeRepo, "worktree_state", outside_transaction(con, FakeRepo.worktree_state))
    patch.setattr(FakeRepo, "worktree", outside_transaction(con, FakeRepo.worktree))
    patch.setattr(FakeWorktree, "dirty", outside_transaction(con, FakeWorktree.dirty))
    patch.setattr(FakeWorktree, "diff", outside_transaction(con, FakeWorktree.diff))
