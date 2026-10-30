"""The close's work on the slot: the branch saved (a wip commit, the checkpoint marked closed), the slot left."""
import contextlib
from pathlib import Path
from typing import Protocol

from taskloop.contracts import fence
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ports import Beads, Sh

DONE = (Outcome.LANDED, Outcome.DONE)


class BranchTree(Protocol):
    def wip(self, why: str, everything: bool = ...) -> bool: ...


class BranchCheckpoints(Protocol):
    def close(self, why: str = ...) -> None: ...


class SaveBranchHost(Protocol):
    """What saving the branch reads of the engine: git and its shell, the run's branch, the wip commit and the closed checkpoint."""

    @property
    def branch(self) -> str: ...
    @property
    def sh(self) -> Sh: ...
    @property
    def tree(self) -> BranchTree: ...
    @property
    def checkpoints(self) -> BranchCheckpoints: ...
    def git(self, *args: str) -> str: ...


class SaveBranch:
    def __init__(self, host: SaveBranchHost) -> None:
        self.e = host

    def run(self, outcome: Outcome, why: str) -> None:
        """A run stopped mid-conflict-fix goes back to its branch; an unfinished branch keeps its work as a wip commit and a
        closed checkpoint."""
        e = self.e
        gd = Path(e.git("rev-parse", "--absolute-git-dir") or ".")
        if (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists():
            e.sh(["git", "rebase", "--abort"], pin=True)
        branch = e.git("symbolic-ref", "--short", "-q", "HEAD")
        if outcome not in DONE and branch and branch == (e.branch or None):
            if e.git("status", "--porcelain"):
                e.tree.wip(outcome)  # the next run continues this branch
            e.checkpoints.close(why)


class LeaveTree(Protocol):
    def leave_slot(self, outcome: str, branch: str) -> None: ...


class ReleaseSlotHost(Protocol):
    """What leaving the slot reads of the engine: the claim and bd (the fence), and the tree that leaves."""

    @property
    def claim(self) -> fence.Claim: ...
    @property
    def store(self) -> Beads: ...
    @property
    def tree(self) -> LeaveTree: ...


class ReleaseSlot:
    def __init__(self, host: ReleaseSlotHost) -> None:
        self.e = host

    def run(self, branch: str, outcome: Outcome) -> None:
        """Last: the trace and the comments read the branch. A slot whose lease moved on (another generation) is not this run's to touch."""
        e = self.e
        with contextlib.suppress(Exception):
            if e.claim.slot_bead and fence.stale(e.store, e.claim):
                return
            e.tree.leave_slot(outcome, branch)
