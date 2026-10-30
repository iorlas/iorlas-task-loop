"""The close's work on the slot: the branch saved (a wip commit, the checkpoint marked closed), the slot left."""
import contextlib
from typing import Protocol

from taskloop.contracts import fence
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ports import Beads, Git

DONE = (Outcome.LANDED, Outcome.DONE)


class BranchTree(Protocol):
    def wip(self, why: str, everything: bool = ...) -> bool: ...


class BranchCheckpoints(Protocol):
    def close(self, why: str = ...) -> None: ...


class SaveBranchHost(Protocol):
    """What saving the branch reads of the engine: git, the run's branch, the wip commit and the closed checkpoint."""

    @property
    def branch(self) -> str: ...
    @property
    def wt(self) -> str: ...
    @property
    def git(self) -> Git: ...
    @property
    def tree(self) -> BranchTree: ...
    @property
    def checkpoints(self) -> BranchCheckpoints: ...


class SaveBranch:
    def __init__(self, host: SaveBranchHost) -> None:
        self.e = host

    def run(self, outcome: Outcome, why: str) -> None:
        """A run stopped mid-conflict-fix goes back to its branch; an unfinished branch keeps its work as a wip commit and a
        closed checkpoint."""
        e = self.e
        if e.git.rebasing(e.wt):
            e.git.rebase_abort(e.wt)
        branch = e.git.branch(e.wt)
        if outcome not in DONE and branch and branch == (e.branch or None):
            if e.git.dirty(e.wt):
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
