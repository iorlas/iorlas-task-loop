"""Slots: why a slot refuses, what git can say about a slot's worktree, and the port the slot code reaches git through.

A slot is one worktree plus the bd bead that is its lease. `Slot.take`, `ready_for` and `release` fail with a `SlotFail`
whose `code` is one of three closed values; git's own failures are the typed `SlotGitError`s below, classified once by the
adapter (the only place that reads git's words), never by the caller.
"""
from typing import Literal, Protocol, final

from taskloop.contracts.wire import Rec

SlotFailCode = Literal["slot_broken", "bead_pinned", "busy"]


class SlotFail(Exception):
    """The slot cannot do what was asked. busy: a live engine, a hold or another claim. bead_pinned: the bead's branch is
    checked out by a live run, so this bead is not for this slot now. slot_broken: git or the worktree is in a state the
    slot cannot clear (a dirty tree it cannot commit, a lock that stays, no such slot)."""

    def __init__(self, code: SlotFailCode, why: str) -> None:
        super().__init__(why)
        self.code: SlotFailCode = code
        self.why = why


class SlotGitError(Exception):
    """git failed in a slot; `tail` is its message's decisive line."""

    def __init__(self, tail: str) -> None:
        super().__init__(tail)
        self.tail = tail


class BranchPinned(SlotGitError):
    """The branch is checked out in another worktree (`where`)."""

    def __init__(self, tail: str, where: str = "") -> None:
        super().__init__(tail)
        self.where = where


class DirtyTree(SlotGitError):
    """The worktree has changes git will not carry over, or could not commit."""


class RefRace(SlotGitError):
    """A ref lock lost to another process writing the same refs; trying again usually works."""


class IndexLocked(SlotGitError):
    """index.lock exists in the worktree's git dir: another git runs there, or one died."""


@final
class Hold(Rec):
    """A slot reserved for a person (tl slot hold): the loop and run-task keep off it until `until`."""

    by: str
    since: str
    why: str
    until: float


@final
class Checkout(Rec):
    """One worktree of a repo (git worktree list): where it is, the branch it has out (empty when detached), the main one."""

    path: str
    branch: str
    main: bool


class SlotGit(Protocol):
    """git as a slot's reset needs it. Every method takes the worktree it acts in and raises a SlotGitError subclass."""

    def fetch(self, d: str) -> None: ...
    def rebasing(self, d: str) -> bool: ...
    def rebase_abort(self, d: str) -> None: ...
    def dirty(self, d: str) -> bool: ...
    def branch(self, d: str) -> str:
        """The branch checked out in `d`, empty when HEAD is detached."""
        ...

    def commit_all(self, d: str, branch: str, message: str) -> None:
        """Commit every change on `branch`, created at HEAD when HEAD is detached."""
        ...

    def has_branch(self, d: str, branch: str) -> bool: ...
    def checkout(self, d: str, branch: str) -> None: ...
    def checkout_new(self, d: str, branch: str, start: str) -> None: ...
    def checkout_detached(self, d: str, ref: str) -> None: ...
    def clean(self, d: str, keep: list[str]) -> None: ...
    def checkouts(self, d: str) -> list[Checkout]: ...
    def remove_worktree(self, repo: str, path: str) -> bool: ...
    def add_worktree(self, repo: str, path: str, ref: str) -> None: ...
