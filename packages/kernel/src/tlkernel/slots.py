"""Slots: why a slot refuses, what git can say about a slot's worktree (the port itself is `Git`, in ports.py).

A slot is one worktree plus the bd bead that is its lease. `Slot.take`, `ready_for` and `release` fail with a `SlotFail`
whose `code` is one of four closed values; git's own failures are the typed `SlotGitError`s below, classified once by the
adapter (the only place that reads git's words), never by the caller.
"""
from collections.abc import Callable, Sequence
from typing import Literal, final

from tlkernel.bead import Bead
from tlkernel.wire import Rec

HELD_KEYS = ("held_by", "held_since", "held_why", "hold_until", "held_bead")  # the marks on a slot bead while it is held
SlotFailCode = Literal["slot_broken", "bead_pinned", "busy", "transient"]


def slots_of(beads: Sequence[Bead], host: str) -> list[Bead]:
    """Nonclosed leases named `slot <host> <name>`, in title order, from an existing listing."""
    return sorted((b for b in beads if "slot" in b.labels and b.status != "closed"
                   and len(b.title.split()) == 3 and b.title.split()[:2] == ["slot", host]), key=lambda b: b.title)


class SlotFail(Exception):
    """The slot cannot do what was asked. busy: a live engine, a hold or another claim. bead_pinned: the bead's branch is
    checked out by a live run, so this bead is not for this slot now. slot_broken: git or the worktree is in a state the
    slot cannot clear (a dirty tree it cannot commit, a lock that stays, no such slot). transient: infrastructure failed,
    without evidence that the slot itself is broken."""

    def __init__(self, code: SlotFailCode, why: str, *, setup: bool = False) -> None:
        super().__init__(why)
        self.code: SlotFailCode = code
        self.why = why
        self.setup = setup  # the slot's setup command exited non-zero (its tree is the suspect, not git)


class SlotGitError(Exception):
    """git failed in a slot; `tail` holds diagnostics, `output` preserves captured stdout and stderr when available."""

    def __init__(self, tail: str, *, output: str | None = None) -> None:
        super().__init__(tail)
        self.tail = tail
        self.output = tail if output is None else output


class GitReadFailure(SlotGitError):
    """Git could not establish an observation; callers must not infer clean, empty or missing."""


class NotARepo(GitReadFailure):
    """Git established that the requested directory is absent or outside a repository."""


class MissingRevision(GitReadFailure):
    """A named revision does not exist; this is not an empty diff."""


class MissingRemote(GitReadFailure):
    """The requested remote is not configured."""


class NotAWorktree(GitReadFailure):
    """The repository has no worktree (for example, a bare repository)."""


def git_probe[T](read: Callable[[], T], unknown: T) -> T:
    """A display or readiness probe's fallback; never use it to authorize writes or skips."""
    try:
        return read()
    except GitReadFailure:
        return unknown


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


SlotState = Literal["free", "claimed", "running", "held", "setup", "dead", "retiring"]


@final
class SlotView(Rec):
    """One slot as every reader shows it (dash account, `tl status` line, doctor row); the state is computed from `now`, not a raw mark."""

    id: str
    state: SlotState
    holder: str = ""  # the live run, the hold's owner or the claim's assignee
    bead: str = ""  # the bead the slot works on or is starting
    since: str = ""
    held_reason: str = ""
    held_until: float = 0.0
    idle_why: str = ""
    dir_exists: bool = True
    beyond_count: bool = False  # the slot's name is above the configured count: it is finishing, no new work goes to it
    pid: int | None = None  # of the live run's process, when a caller knows it


@final
class SlotTable(Rec):
    """The slots of one repo on one machine. The count is `len(slots)`: there is no second number to disagree with."""

    configured: int  # slots.count of the profile read from `source`
    slots: list[SlotView]
    source: str  # the base ref the profile was read from (origin/main), or "worktree" when that ref does not resolve
    source_sha: str = ""
    v: int = 1
