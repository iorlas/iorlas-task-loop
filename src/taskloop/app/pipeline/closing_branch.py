"""The close's work on the slot: the branch saved (a wip commit, the checkpoint marked closed), the slot left."""
import traceback
from collections.abc import Callable
from typing import Protocol

from taskloop.app.pipeline.outcomes import DONE
from taskloop.app.pipeline.ports import LandCleanup, Slotting
from taskloop.contracts import fence
from taskloop.contracts.beadsport import Beads
from taskloop.contracts.enums import Outcome
from taskloop.contracts.gitport import Git
from taskloop.stores.runlog import RunLog


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
    def __init__(self, host: SaveBranchHost, after_save: Callable[[], None] | None = None) -> None:
        self.host = host
        self.after_save = after_save

    def run(self, outcome: Outcome, why: str) -> None:
        """A run stopped mid-conflict-fix goes back to its branch; an unfinished branch keeps its work as a wip commit and a
        closed checkpoint."""
        e = self.host
        if e.git.rebasing(e.wt):
            e.git.rebase_abort(e.wt)
        branch = e.git.branch(e.wt)
        if outcome not in DONE and branch and branch == (e.branch or None):
            if e.git.dirty(e.wt) and e.tree.wip(outcome) and self.after_save is not None:  # the next run continues this branch
                self.after_save()
            e.checkpoints.close(why)


class ReleaseSlotHost(Protocol):
    """What leaving the slot reads of the engine: the claim and bd (the fence), and the tree that leaves."""

    @property
    def claim(self) -> fence.Claim: ...
    @property
    def store(self) -> Beads: ...
    @property
    def git(self) -> Git: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def wt(self) -> str: ...


class ReleaseSlot:
    def __init__(self, host: ReleaseSlotHost, slotting: Slotting, cleanup: LandCleanup) -> None:
        self.host = host
        self.slotting = slotting
        self.cleanup = cleanup

    def run(self, branch: str, outcome: Outcome) -> None:
        """Last: the trace and the comments read the branch. A slot whose lease moved on (another generation) is not this run's to touch."""
        e = self.host
        try:
            if e.claim.slot_bead and fence.stale(e.store, e.claim):
                return
            self.slotting.leave_slot(outcome, branch)
            if outcome is Outcome.LANDED:
                repo = next((co.path for co in e.git.checkouts(e.wt) if co.main), e.wt)
                self.cleanup.retry(repo)
        except Exception as err:
            e.log.warn(f"could not release slot: {err}\n" + traceback.format_exc())
