"""A resumed branch is rebased onto the latest base before it is planned. A conflict in few files is fixed in place (land/salvage.py),
else the task starts again on the base (land/restart.py)."""
from collections.abc import Callable
from typing import Protocol

from taskloop.contracts.checkpoint import Checkpoint, PlanStep
from taskloop.contracts.ports import Sh
from taskloop.stores.runlog import RunLog

MAX_REBASE_RESETS = 2  # the plan count starts again at most this often per bead: a red gate for a real reason must still reach the limit
SALVAGE_MAX_FILES = 10  # a resume conflict in more files than this starts again


class RebaseConfig(Protocol):
    @property
    def base(self) -> str: ...


class RebaseCheckout(Protocol):
    def dirty_status(self) -> str: ...


class RebaseCheckpoints(Protocol):
    def amend(self, fn: Callable[[Checkpoint], Checkpoint]) -> bool: ...
    def drop(self) -> None: ...


class RebaseHost(Protocol):
    """What the resume rebase reads of the engine: git and its shell, the base, the checkout's dirt, the checkpoint it follows, and the
    plan count a move to a new base starts again."""

    left_dirty: bool
    rebase_orig: str  # the branch's head before the rebase, for start_again
    rebase_pre: list[str]  # the heads the checkpoint may name before the rebase
    salvage_tail: str  # the conflict's words for the fix round
    planned: int
    rebase_resets: int
    plan_log: list[PlanStep]

    @property
    def bead(self) -> str: ...
    @property
    def dry(self) -> bool: ...
    @property
    def cfg(self) -> RebaseConfig: ...
    @property
    def sh(self) -> Sh: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def checkout(self) -> RebaseCheckout: ...
    @property
    def checkpoints(self) -> RebaseCheckpoints: ...
    def git(self, *args: str) -> str: ...
    def warn(self, text: str) -> None: ...


class Rebase:
    def __init__(self, host: RebaseHost) -> None:
        self.e = host
        self.squashed = False
        self.between = False

    def onto_base(self, salvage: bool = False, between: bool = False) -> str:
        """tl-bxk.13.8: a branch resumed from an earlier run is rebased onto the latest base before it is planned or re-planned, so the
        plan and the checks see what main has now. -> "rebased" (the plan count starts again), "conflict" (the work does not fit main: the
        caller starts again, tl-19i), "conflict-fixable" (salvage on: the rebase stopped on few files and is left running for the caller's
        fix(conflict)), or "". More than one commit on the branch (the wip commits) is squashed first, so one conflict is fixed once.
        tl-7y6.23: between=True is the same between two stages of a run: the plan stays, so its count does not start again."""
        e = self.e
        self.between = between
        if e.dry or e.checkout.dirty_status():  # (the base-ignored files of an old branch are no reason not to rebase)
            return ""
        behind = e.git("rev-list", "--count", f"HEAD..{e.cfg.base}")
        if behind in ("", "0"):
            return ""
        orig = e.git("rev-parse", "HEAD")
        old_parent = e.git("rev-parse", "-q", "--verify", "HEAD~1") if e.left_dirty else ""
        self.squash_wip(orig)
        e.rebase_orig, e.rebase_pre = orig, [x for x in (orig, old_parent) if x]
        rc, tail = e.sh(["git", "rebase", "-q", e.cfg.base], pin=True)
        if rc:
            return self.stopped(salvage, tail, orig)
        self.follow_checkpoint()
        when = "between stages" if between else "before planning"
        e.log.note(f"rebased the task branch onto the latest {e.cfg.base} ({behind} commits behind) {when}")
        return self.plan_count()

    def squash_wip(self, orig: str) -> None:
        e = self.e
        self.squashed = False
        mb = e.git("merge-base", "HEAD", e.cfg.base)
        if not mb or e.git("rev-list", "--count", f"{mb}..HEAD") in ("", "0", "1"):
            return
        rc, _ = e.sh(["git", "reset", "-q", "--soft", mb], pin=True)
        if not rc:
            rc, _ = e.sh(["git", "commit", "-q", "--no-verify", "--allow-empty", "-m", f"wip ({e.bead}): earlier work, squashed"], pin=True)
        if rc:  # the branch stays as it was
            e.sh(["git", "reset", "-q", "--hard", orig], pin=True)
        else:
            self.squashed = True
            e.log.note("squashed the branch's wip commits into one before rebasing")

    def stopped(self, salvage: bool, tail: str, orig: str) -> str:
        e = self.e
        unmerged = e.git("diff", "--name-only", "--diff-filter=U").split()
        if salvage and unmerged and len(unmerged) <= SALVAGE_MAX_FILES:
            e.salvage_tail = "Conflicted files: {}\n{}".format(", ".join(unmerged), tail)
            return "conflict-fixable"
        e.sh(["git", "rebase", "--abort"], pin=True)
        if self.squashed:
            e.sh(["git", "reset", "-q", "--hard", orig], pin=True)
        last = tail.strip().splitlines()[-1][:200] if tail.strip() else "conflict"
        e.warn(f"the task branch could not be rebased onto {e.cfg.base} before planning: {last}")
        return "conflict"

    def follow_checkpoint(self) -> None:
        """The checkpoint's head follows a rebase (or squash), or the next resume reads this as an edit from outside."""
        e = self.e

        def move(ck: Checkpoint) -> Checkpoint:
            if ck.head not in e.rebase_pre:
                return ck
            # unsquashed, the wip commit reset() made on top of the checkpoint's head is still on top of it
            above = not self.squashed and len(e.rebase_pre) > 1 and ck.head == e.rebase_pre[1]
            return ck.replace(head=e.git("rev-parse", "HEAD~1" if above else "HEAD"))

        e.checkpoints.amend(move)

    def plan_count(self) -> str:
        e = self.e
        if self.between:
            return "rebased"
        if e.planned and e.rebase_resets < MAX_REBASE_RESETS:
            # tl-19i: plans made on the old base say nothing about this one. At most twice per bead
            e.log.note(f"the plan count starts again: {e.planned} earlier plan{'' if e.planned == 1 else 's'} were made on another base")
            e.plan_log.append(PlanStep(mode="rebase", counted=False,
                                       why=f"the branch moved to a new base; {e.planned} plan(s) before it do not count"))
            e.planned, e.rebase_resets = 0, e.rebase_resets + 1
        return "rebased"
