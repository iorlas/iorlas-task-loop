"""Resume and landing rebases, retry checks, task commits, and git failure handling."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from tlgate.api import evidence as check_evidence
from tlkernel import plancheck
from tlkernel.bead import Bead
from tlkernel.checkpoint import Checkpoint, PlanStep
from tlkernel.checks import CheckRun
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.matchers import NetText
from tlkernel.plancheck import PlanData, StageData
from tlkernel.slots import SlotGitError

from taskloop.app.land import gate
from taskloop.app.land.gate import Problem, ProblemKind
from taskloop.app.land.host import BeginSteps, CaseChecks, LandState, OutcomeSteps, StageCheckout, Strays
from taskloop.app.land.push import LandedConfig
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
    """What the resume rebase reads of the engine: git, the base, the checkout's dirt, the checkpoint it follows, and the
    plan count a move to a new base starts again."""

    left_dirty: bool
    land_state: LandState
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
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def checkout(self) -> RebaseCheckout: ...
    @property
    def checkpoints(self) -> RebaseCheckpoints: ...
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
        behind = e.git.count(e.wt, [e.cfg.base], ["HEAD"])
        if behind == 0:
            return ""
        orig = e.git.rev_parse(e.wt, "HEAD")
        old_parent = e.git.rev_parse(e.wt, "HEAD~1") if e.left_dirty else ""
        self.squash_wip(orig)
        e.land_state.rebase_orig, e.land_state.rebase_pre = orig, [x for x in (orig, old_parent) if x]
        done = e.git.rebase(e.wt, e.cfg.base)
        if not done.ok:
            return self.stopped(salvage, done.output, orig)
        self.follow_checkpoint()
        when = "between stages" if between else "before planning"
        e.log.note(f"rebased the task branch onto the latest {e.cfg.base} ({behind} commits behind) {when}")
        return self.plan_count()

    def squash_wip(self, orig: str) -> None:
        e = self.e
        self.squashed = False
        mb = e.git.merge_base(e.wt, "HEAD", e.cfg.base)
        if not mb or e.git.count(e.wt, ["HEAD"], [mb]) <= 1:
            return
        try:
            e.git.reset(e.wt, mb, "soft")
            ok = e.git.try_commit(e.wt, f"wip ({e.bead}): earlier work, squashed", verify=False, allow_empty=True).ok
        except SlotGitError:
            ok = False
        if not ok:  # the branch stays as it was
            e.git.reset(e.wt, orig, "hard")
        else:
            self.squashed = True
            e.log.note("squashed the branch's wip commits into one before rebasing")

    def stopped(self, salvage: bool, tail: str, orig: str) -> str:
        e = self.e
        unmerged = e.git.unmerged(e.wt)
        if salvage and unmerged and len(unmerged) <= SALVAGE_MAX_FILES:
            e.land_state.salvage_tail = "Conflicted files: {}\n{}".format(", ".join(unmerged), tail)
            return "conflict-fixable"
        e.git.rebase_abort(e.wt)
        if self.squashed:
            e.git.reset(e.wt, orig, "hard")
        last = tail.strip() or "conflict"
        e.warn(f"the task branch could not be rebased onto {e.cfg.base} before planning: {last}")
        return "conflict"

    def follow_checkpoint(self) -> None:
        """The checkpoint's head follows a rebase (or squash), or the next resume reads this as an edit from outside."""
        e = self.e

        def move(ck: Checkpoint) -> Checkpoint:
            if ck.head not in e.land_state.rebase_pre:
                return ck
            # unsquashed, the wip commit reset() made on top of the checkpoint's head is still on top of it
            above = not self.squashed and len(e.land_state.rebase_pre) > 1 and ck.head == e.land_state.rebase_pre[1]
            return ck.replace(head=e.git.rev_parse(e.wt, "HEAD~1" if above else "HEAD"))

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


class LandRebaseHost(Protocol):
    """What the land's rebase reads of the engine: the base, git, the step's outcome."""

    @property
    def cfg(self) -> LandedConfig: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def steps(self) -> OutcomeSteps: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class LandRebase:
    def __init__(self, host: LandRebaseHost) -> None:
        self.e = host

    def run(self, fetched: int, tail: str) -> Problem | None:
        e = self.e
        ok = fetched == 0
        if ok:
            done = e.git.rebase(e.wt, e.cfg.base)
            ok, tail = done.ok, done.output
        if ok:
            return None
        unmerged = e.git.unmerged(e.wt)
        if not unmerged:
            e.git.rebase_abort(e.wt)
            raise e.blocked_for(f"failed: fetch or rebase onto {e.cfg.base} failed; branch kept\n{tail}", "FAULT_LAND")
        e.steps.outcome("conflict", ", ".join(unmerged))
        return Problem(ProblemKind.CONFLICT, "Conflicted files: {}\n{}".format(", ".join(unmerged), tail))


class RecheckStageChecks(Protocol):
    def stoppable(self, st: StageData, name: str) -> CheckRun: ...


class RecheckCheckpoints(Protocol):
    def save(self, *, step: str = ..., stage: int = ..., rounds: int = ..., n: int = ..., feedback: str = ...) -> None: ...


class RecheckHost(Protocol):
    """What the retry checks read of the engine: the plan and the cases, the checks and their stop, the barrier and its checkpoint."""

    pending_land_validation: str  # set while the land's retry checks still need accepted checks and review

    @property
    def plan_data(self) -> PlanData | None: ...
    @property
    def run_dir(self) -> Path: ...
    @property
    def cases(self) -> CaseChecks: ...
    @property
    def stage_checks(self) -> RecheckStageChecks: ...
    @property
    def checkpoints(self) -> RecheckCheckpoints: ...
    @property
    def steps(self) -> BeginSteps: ...
    def stop_deferred(self) -> AbstractContextManager[list[bool]]: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...
    def move_host(self, needs: list[str], why: str) -> Exception: ...


class Recheck:
    def __init__(self, host: RecheckHost) -> None:
        self.e = host

    def run(self, tries: int) -> Problem | None:
        """Repo checks reuse their input cache; stage/case checks stay conservative because they can depend on state outside the
        tracked tree. `tries`: the push tries so far, for the land step's text."""
        e = self.e
        stages = plancheck.stages_of(e.plan_data)
        checks = list(dict.fromkeys([*(c for s in stages for c in s["checks"]), *e.cases.case_checks()]))
        # A stop during checks or just after they return must resume through acceptance: save that barrier first
        self.park("land retry checks require successful checks and review before landing", "land-verify-red")
        results = e.stage_checks.stoppable({"checks": checks, "files": []}, "land retry")
        gate.refuse(results, e)
        bad = results.failed
        problem = Problem(ProblemKind.VERIFY, check_evidence.failure_brief(bad, e.run_dir)) if bad else None
        self.park(problem.text if problem else "", "land-verify-red" if bad else "land")
        e.steps.begin("land", f"land (try {tries + 1})", **{"try": tries + 1})
        return problem

    def park(self, pending: str, step: str) -> None:
        """Save the barrier with SIGTERM deferred; a stop that came meanwhile ends the run after the save."""
        e = self.e
        with e.stop_deferred() as stop:
            e.pending_land_validation = pending
            e.checkpoints.save(stage=len(plancheck.stages_of(e.plan_data)), step=step)
        if stop:
            raise e.blocked_for("failed: stopped (SIGTERM)", "PAUSE_KILLED")


class CommitHost(Protocol):
    """What the commit reads of the engine: the bead, git, the staging and the strays."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def checkout(self) -> StageCheckout: ...
    @property
    def newfiles(self) -> Strays: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class Commit:
    def __init__(self, host: CommitHost) -> None:
        self.e = host

    def run(self, bead: Bead, base_ref: str) -> bool:
        """One commit per task, titled after the bead. -> False: the wip commits add up to nothing."""
        e = self.e
        base = e.git.merge_base(e.wt, "HEAD", base_ref)
        if base:
            must(e, f"reset --soft {base}", lambda: e.git.reset(e.wt, base, "soft"))
        e.checkout.stage_all(check=True)
        e.newfiles.quarantine_strays()
        if base and not e.git.staged(e.wt):
            return False
        done = e.git.try_commit(e.wt, f"{bead.title[:72]} ({e.bead})")
        if not done.ok:
            raise e.blocked_for("failed: commit refused (hooks)\n" + done.output, "FAULT_LAND")
        return True


class BlockedFor(Protocol):
    def blocked_for(self, why: str, kind: str) -> Exception: ...


def must[T](e: BlockedFor, what: str, call: Callable[[], T], kind: str = "FAULT_INFRA") -> T:
    """`call()`; a git failure raises `e.blocked_for("failed: `git <what>`: <git's words>")` (the run stops, the branch is kept)."""
    try:
        return call()
    except SlotGitError as err:
        down = kind == "FAULT_INFRA" and NetText.down(str(err))
        raise e.blocked_for(f"{'paused' if down else 'failed'}: `git {what}`: {err}", "PAUSE_NETWORK" if down else kind) from err


def oneline(git: Git, d: str, include: list[str], exclude: list[str], limit: int) -> str:
    """The newest `limit` commits of `include` not on `exclude`, one `<short oid> <subject>` per line; empty when git cannot say."""
    try:
        return "\n".join(f"{r.oid[:7]} {r.subject}" for r in git.log(d, include, exclude, limit=limit))
    except SlotGitError:
        return ""
