"""Fix land failures under the stage loop checks and review, outside the land lock before retrying."""
from collections.abc import Sequence
from types import MappingProxyType
from typing import ClassVar, Final, Protocol

from tlgate.api import evidence as check_evidence
from tlgate.api import planref
from tlkernel import askspecs, plancheck
from tlkernel import checktrim as trim
from tlkernel.askspec import AskSpec
from tlkernel.checks import CheckResult
from tlkernel.config import EngineConfig
from tlkernel.gitport import Git
from tlkernel.plancheck import PlanCheck, PlanData, RoundState, StageData
from tlkernel.ports import Sh

from taskloop.app.land.gate import Problem, ProblemKind
from taskloop.app.land.host import CaseChecks, LandState, MoveSteps, StageCheckout
from taskloop.app.land.rebase import must
from taskloop.domain.land.fix_text import FIX_GOAL as GOAL
from taskloop.domain.land.fix_text import FIX_TEXT as TEXT
from taskloop.domain.land.fix_text import FIX_WHAT as WHAT


class FixerCheckpoints(Protocol):
    def save(self, *, step: str = ..., stage: int = ..., rounds: int = ..., n: int = ..., feedback: str = ...) -> None: ...


class FixerStageLoop(Protocol):
    def run(self, plan: PlanData, i: int, state: RoundState | None = ...) -> str: ...


class FixerHost(Protocol):
    """What a fix round reads of the engine: the rounds used, the plan and its cases, the repo's config, the stage loop that runs the fix,
    the checkpoint, git, its shell for the conflict-marker check, and the gate's log."""

    fixes: int
    land_state: LandState
    MARKERS: ClassVar[str]
    MARKERS_ARGV: ClassVar[Sequence[str]]

    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def plan_data(self) -> PlanData | None: ...
    @property
    def cases(self) -> CaseChecks: ...
    @property
    def stage_loop(self) -> FixerStageLoop: ...
    @property
    def checkpoints(self) -> FixerCheckpoints: ...
    @property
    def checkout(self) -> StageCheckout: ...
    @property
    def sh(self) -> Sh: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    def warn(self, text: str) -> None: ...
    def blocked_for(self, why: str, kind: str, stop: object = ..., spec: AskSpec | None = ..., fix: bool = ...) -> Exception: ...


class Fixer:
    def __init__(self, host: FixerHost) -> None:
        self.e = host

    def fix(self, kind: str, tail: str, resume: bool = False) -> str:
        """Write, check (a conflict fix: markers and build only; else every stage's checks again), review the fix only. A gate fix is folded
        into the task's commit; a conflict fix continues the rebase; a verify fix stays in the tree. max_fix_rounds per bead, then stuck.
        Returns the fix stage's end. `resume`: the conflict is the resume rebase's (tl-7y6.2.19), so the checkpoint stays where it is."""
        e = self.e
        e.fixes += 1
        limit = e.cfg.max_fix_rounds
        if e.fixes > limit:
            self.give_up(kind, tail, limit)
        e.warn(f"{'resume' if resume else 'land'}: {WHAT[kind]}, fix round {e.fixes} of {limit}")
        if not resume:
            e.checkpoints.save(stage=len(plancheck.stages_of(e.plan_data)), step="land")
        done = e.stage_loop.run({"stages": [self.stage(kind)]}, 0, self.round_state(kind, tail, limit))
        if kind == "conflict":
            return self.continue_rebase(done, tail, resume)
        if kind == "gate" and e.git.dirty(e.wt):
            e.checkout.stage_all(check=True)
            must(e, "commit --amend", lambda: e.git.amend(e.wt))
        if done != "accept" and kind != "verify":
            e.warn("land: the fix round did not pass its checks and review; landing tries the gate again")
        return done

    def give_up(self, kind: str, tail: str, limit: int) -> None:
        e = self.e
        if kind == "conflict":
            e.git.rebase_abort(e.wt)
        trimmed = trim.trim_log(tail, log=str(e.land_state.gate_log or "") if kind == "gate" else "")
        raise e.blocked_for(f"{WHAT[kind]} after {limit} fix rounds: it needs the owner's hint\n{trimmed}", "ASK_STUCK",
                            spec=askspecs.no_progress(WHAT[kind], limit, trimmed), fix=kind == "conflict")

    def stage(self, kind: str) -> StageData:
        """The fix as a one-stage plan. A conflict fix checks markers and build only: the plan's checks are skipped (tl-7y6.2.18)."""
        e = self.e
        checks: list[PlanCheck] = list(dict.fromkeys(c for s in plancheck.stages_of(e.plan_data) for c in s["checks"]))
        if kind == "conflict":
            checks = [plancheck.adhoc(e.MARKERS)]
        return {"goal": "Fix: " + GOAL[kind], "files": [], "checks": checks, "hard": False}

    def round_state(self, kind: str, tail: str, limit: int) -> RoundState:
        e = self.e
        skip = None
        if kind == "conflict":
            checks = [c for s in plancheck.stages_of(e.plan_data) for c in s["checks"]]
            skip = planref.commands([*checks, *e.cases.case_checks()], e.cfg)
        return {"fix": True, "conflict_fix": skip, "name": f"fix {e.fixes}/{limit}", "fix_n": e.fixes, "fix_of": limit,
                "failed": [e.cfg.gate_text or "rebase"] if kind == "gate" else None, "feedback": self.feedback(kind, tail),
                "scope": f"the fix only: it must {GOAL[kind]} without breaking what the accepted stages built"}

    def feedback(self, kind: str, tail: str) -> str:
        e = self.e
        if kind == "verify":
            return TEXT[kind].format(tail)
        if kind == "conflict":
            return TEXT[kind].format("", check_evidence.compact([CheckResult.failed_run("rebase", tail)]))
        gate = f" (`{e.cfg.gate_text}`)" if e.cfg.gate_checks else ""
        return TEXT[kind].format(gate, tail)  # the gate's text is already the red steps' brief (Gate.run)

    def continue_rebase(self, done: str, tail: str, resume: bool) -> str:
        e = self.e
        if e.sh([*e.MARKERS_ARGV], pin=True)[0]:
            return self.fix("conflict", "conflict markers are still in the tree after the fix", resume=resume)
        e.checkout.stage_all(check=True)
        went = e.git.rebase_continue(e.wt)
        if not went.ok:
            e.git.rebase_abort(e.wt)
            raise e.blocked_for("failed: the rebase did not continue after the conflict fix\n" + went.output, "FAULT_LAND", fix=True)
        if done != "accept":
            e.warn("land: the fix round did not pass its checks and review; landing tries the gate again")
        return done


class FixRounds(Protocol):
    def fix(self, kind: str, tail: str, resume: bool = ...) -> str: ...


class FixConfig(Protocol):
    @property
    def max_fix_rounds(self) -> int: ...


class FixCheckpoints(Protocol):
    def save(self, *, step: str = ..., stage: int = ..., rounds: int = ..., n: int = ..., feedback: str = ...) -> None: ...


class FixOutsideHost(Protocol):
    """What fixing outside the lock reads of the engine: the fix rounds used and allowed, the fixer, the plan's stage count, the barrier
    and its checkpoint, git, the staging and the amend."""

    pending_land_validation: str  # set while the land's retry checks still need accepted checks and review
    fixes: int
    stuck_why: str

    @property
    def cfg(self) -> FixConfig: ...
    @property
    def steps(self) -> MoveSteps: ...
    @property
    def fixer(self) -> FixRounds: ...
    @property
    def plan_data(self) -> PlanData | None: ...
    @property
    def checkpoints(self) -> FixCheckpoints: ...
    @property
    def checkout(self) -> StageCheckout: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


# A stale gate is retried without a fix round.
CAUSE: Final = MappingProxyType({
    ProblemKind.GATE: "gate_red", ProblemKind.VERIFY: "checks_red", ProblemKind.CONFLICT: "conflict", ProblemKind.STALE: None,
})


class FixOutside:
    def __init__(self, host: FixOutsideHost) -> None:
        self.e = host

    def run(self, problem: Problem) -> None:
        e = self.e
        cause = CAUSE[problem.kind]
        if cause is None:
            return
        if e.fixes < e.cfg.max_fix_rounds:
            first = problem.text.strip().splitlines() or [""]
            red = f"gate red on the rebased tree: {problem.named or first[-1]}"
            e.steps.move("fix", cause, red if problem.kind is ProblemKind.GATE else problem.text.splitlines()[0])
        fixed = e.fixer.fix(problem.kind, problem.text)
        stages = len(plancheck.stages_of(e.plan_data))
        if problem.kind is ProblemKind.VERIFY and fixed != "accept":
            e.pending_land_validation += "\n" + e.stuck_why
            e.checkpoints.save(stage=stages, step="land-verify-red")
            raise e.blocked_for("land retry validation fix did not pass its checks and review; branch kept", "FAULT_LAND")
        if problem.kind is ProblemKind.VERIFY:
            e.pending_land_validation = ""
            e.checkpoints.save(stage=stages, step="land")
            if e.git.dirty(e.wt):  # unlike verification before finish(), a retry check's fix follows the task commit
                e.checkout.stage_all(check=True)
                must(e, "commit --amend", lambda: e.git.amend(e.wt))
