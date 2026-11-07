"""Record a land and its follow-ups, salvage a resume rebase, and restart conflicting work on the base."""

import time
from collections.abc import Mapping, Sequence
from functools import cached_property
from typing import Protocol, assert_never

from tlkernel import closeeffects as effects
from tlkernel import followkeys as fu
from tlkernel.beadsport import BdFailure, BeadQuery, Beads, NewBead
from tlkernel.checkpoint import RunState
from tlkernel.effectinterpret import CheckpointLedger, interpret
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.slots import SlotGitError

from taskloop.adapters import bdcreate
from taskloop.app.asks import deferral as intake
from taskloop.app.land.host import LandState, MoveSteps
from taskloop.app.land.rebase import Rebase, must
from taskloop.stores.runlog import RunLog


class SyncCheckpoints(Protocol):
    def applied(self) -> frozenset[str]: ...
    def mark_applied(self, key: str) -> None: ...


class BdSync(Protocol):
    def bd_sync(self, sha: str) -> None: ...


class SyncHost(Protocol):
    """What the after-steps read of the engine: the bead, the run's id (its log path), the dry flag, the ledger in the checkpoint and the
    landed record."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def dry(self) -> bool: ...
    @property
    def run_id(self) -> str: ...
    @property
    def checkpoints(self) -> SyncCheckpoints: ...
    def record_land(self, sha: str) -> None: ...


class Sync:
    def __init__(self, host: SyncHost, out: BdSync) -> None:
        self.e = host
        self.out = out

    @cached_property
    def ledger(self) -> CheckpointLedger:
        return CheckpointLedger(self.e.checkpoints)

    def run(self, sha: str) -> str:
        """The land is done and the lock is let go. -> sha."""
        e = self.e
        if sha and not e.dry:
            interpret(e.bead, e.run_id, effects.plan_land(sha), self.ledger, self.apply)
        return sha

    def apply(self, eff: effects.LandEffect) -> None:
        match eff:
            case effects.RecordLand():
                self.e.record_land(eff.sha)
            case effects.BdSync():
                self.out.bd_sync(eff.sha)
            case _:
                assert_never(eff)


class SalvageFixer(Protocol):
    def fix(self, kind: str, tail: str, resume: bool = ...) -> str: ...


class SalvageHost(Protocol):
    """What the salvage reads of the engine: git, the conflict's words and the head before the rebase, the one fix round it
    may ask for (the land's own two stay as they were)."""

    land_state: LandState
    fixes: int

    @property
    def FixFailed(self) -> type[Exception]: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def fixer(self) -> SalvageFixer: ...
    def warn(self, text: str) -> None: ...


class Salvage:
    def __init__(self, host: SalvageHost, rebase: Rebase) -> None:
        self.e = host
        self.rebase = rebase

    def salvage(self) -> str:
        """tl-7y6.2.19: the resume rebase stopped on a few files: one fix(conflict) round (markers and build only) instead of throwing the
        branch away. -> "rebased" (the run record shows salvaged: true), or "conflict": the fix did not work, the branch is back as it
        was and the caller starts again."""
        e = self.e
        fixes, ok = e.fixes, False
        try:
            d = e.fixer.fix("conflict", e.land_state.salvage_tail, resume=True)
            ok = not e.git.unmerged(e.wt)  # (a fix the review sent back still continued the rebase)
            if d != "accept":
                e.warn("resume: the conflict fix did not pass its checks and review; the stage goes on from it")
        except e.FixFailed as err:
            e.warn(f"the resume conflict fix failed: {err}")
        finally:
            e.fixes = fixes  # the land's two fix rounds are its own
        if e.git.rebasing(e.wt):
            e.git.rebase_abort(e.wt)
        if not ok:
            e.git.reset(e.wt, e.land_state.rebase_orig, "hard")  # the work as it was, for a fresh attempt
            return "conflict"
        e.land_state.salvaged = True
        self.rebase.follow_checkpoint()
        e.log.note("resume conflict fixed in place instead of starting again (salvaged)")
        return self.rebase.plan_count()


class WriteHeld(Protocol):
    last_summary: str  # the write stage's (engine.write): the restart forgets it


class RestartConfig(Protocol):
    @property
    def base(self) -> str: ...


class RestartCheckpoints(Protocol):
    def drop(self) -> None: ...


class RestartReview(Protocol):
    """The engine's `review` as a restart clears it."""

    unverified: list[dict[str, str]]
    unchecked: list[dict[str, str]]


class AmendHeld(Protocol):
    """The engine's `amend` (the plan stage's amendment context) as a restart clears it."""

    def clear(self) -> None: ...


class RestartHost(Protocol):
    """What a restart on the base reads of the engine: git, the branch, the checkpoint it drops, and the run's plan
    bookkeeping that the old attempt leaves and a restart clears."""

    amend: AmendHeld
    replan_first: bool
    plan_summary: str
    write: WriteHeld
    state: RunState
    review: RestartReview

    @property
    def wt(self) -> str: ...
    @property
    def branch(self) -> str: ...
    @property
    def cfg(self) -> RestartConfig: ...
    @property
    def git(self) -> Git: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def steps(self) -> MoveSteps: ...
    @property
    def checkpoints(self) -> RestartCheckpoints: ...
    def restarted(self) -> RunState: ...
    def warn(self, text: str) -> None: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...
    def comment(self, text: str) -> None: ...


class Restart:
    def __init__(self, host: RestartHost) -> None:
        self.e = host

    def again(self, why: str) -> bool:
        """tl-19i: the branch's earlier work conflicts with main, so it cannot go on. It is kept under another name; the task starts again
        on the base with a fresh plan (the owner's answer is in the bead's comments), and nothing so far counts toward the re-plan limit."""
        e = self.e
        branch = e.git.branch(e.wt)
        if not branch or branch != (e.branch or branch):
            e.warn(f"resume conflict, but HEAD is not the task branch ({branch or 'detached'}): the branch stays as it was")
            return False
        stale = f"{branch}-stale-{time.strftime('%Y%m%d-%H%M%S')}"
        if e.git.has_branch(e.wt, stale):
            stale += "-2"
        try:
            e.git.rename_branch(e.wt, branch, stale)
        except SlotGitError as err:  # never reset a branch whose work could not be kept
            e.warn(f"resume conflict, but the branch could not be kept aside ({str(err).strip()}): it stays as it was")
            return False
        must(e, f"checkout -B {branch} {e.cfg.base}", lambda: e.git.checkout_reset(e.wt, branch, e.cfg.base))
        e.checkpoints.drop()
        self.forget()
        e.steps.move("plan", "resume_conflict",
                     f"the branch's earlier work conflicts with {e.cfg.base}: kept as {stale}, planning fresh. {why}")
        e.log.note(f"resume conflict: {branch} kept as {stale}; the task starts again on {e.cfg.base}")
        e.comment(f"Resume (engine): the earlier work on {branch} conflicts with {e.cfg.base}. It is kept as the branch {stale}; "
                  f"the task starts again on {e.cfg.base} with a fresh plan.")
        return True

    def forget(self) -> None:
        """What the old attempt left in the run: the plan, the accepted stages, the writer, the look state (verify_answer stays: the owner's
        word still goes to the planner)."""
        e = self.e
        e.amend.clear()
        e.replan_first = False
        e.plan_summary = ""
        e.write.last_summary = ""
        e.state = e.restarted()
        e.review.unverified = list[dict[str, str]]()
        e.review.unchecked = list[dict[str, str]]()


class FollowUpCheckpoints(Protocol):
    def keep_filed(self, lost: list[dict[str, str]] | None = ...) -> None: ...
    def keep_pending(self, origin: str = ...) -> None: ...


class FollowUpHost(Protocol):
    """What filing follow-ups reads of the engine: the bead, the leftovers and the keys filed so far, bd, the poster, the log."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def store(self) -> Beads: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def stats(self) -> Mapping[str, int]: ...
    @property
    def leftovers(self) -> Sequence[Mapping[str, str]]: ...
    @property
    def filed(self) -> list[str]: ...
    @property
    def followup_ids(self) -> dict[str, str]: ...
    @property
    def checkpoints(self) -> FollowUpCheckpoints: ...
    @property
    def intake_per_day(self) -> int: ...

    def comment(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...


def named(los: Sequence[Mapping[str, str]]) -> str:
    return "; ".join(f"{lo['title']} ({lo['why'][:120]})" for lo in los)


def file_follow_ups(e: FollowUpHost) -> list[dict[str, str]]:
    """-> the ones bd refused. Resolve the bead's exact key before creating, including closed beads."""
    e.checkpoints.keep_pending()
    todo = fu.batch(e.bead, e.leftovers, e.filed)
    unfiled: list[dict[str, str]] = []
    for lo in todo.file:
        key = str(fu.FollowKey.of(e.bead, lo))
        try:
            rows = e.store.find(BeadQuery(label=fu.key_label(e.bead, lo), include_closed=True))
            made, err = (str(rows[0].id), "") if rows else bdcreate.create_checked(e.store, NewBead(
                title=lo["title"], description=lo["why"], deps=["discovered-from:" + e.bead],
                labels=fu.labels(e.bead, e.stats["rounds"], lo) + ([intake.FROM_REVIEW] if e.intake_per_day > 0 else []),
                no_inherit_labels=True), e.bead, e.log.note)
            if made and not rows and e.intake_per_day > 0:
                intake.defer(e.store, BeadId(made))
        except BdFailure as failure:
            made, err = "", failure.error.text  # an unavailable lookup is never permission to create a duplicate
        if made:
            e.filed.append(key)
            e.followup_ids[key] = made
            e.checkpoints.keep_filed()
        else:
            unfiled.append(dict(lo))
            e.warn(f"follow-up not filed: {lo['title'][:80]}: {err}")
    if unfiled:
        e.comment(f"Follow-up (engine): bd refused {len(unfiled)} follow-up(s), none was filed: {named(unfiled)}")
        e.checkpoints.keep_filed(unfiled)
    if todo.over:
        e.comment(f"Follow-up (engine): not filed, the cap is {fu.FOLLOW_UP_CAP} per run; {len(todo.over)} more: {named(todo.over)}")
        e.warn(f"{len(todo.over)} follow-up(s) remain in the durable outbox beyond this run's cap")
    return unfiled
