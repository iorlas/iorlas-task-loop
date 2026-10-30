"""One fix round at land: the writer fixes what the land found wrong (a red gate on the rebased tree, a merge conflict, what the verifier
found), under the stage loop's checks and review, without undoing what the accepted stages built."""
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Protocol

from taskloop.app.checks import evidence as check_evidence
from taskloop.app.land.gitcall import must
from taskloop.app.land.parts import CaseChecks, StageCheckout
from taskloop.contracts import plancheck
from taskloop.contracts.checks import CheckResult
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.plancheck import PlanCheck, PlanData, RoundState, StageData
from taskloop.contracts.ports import Git, Sh
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.checks import planref, trim
from taskloop.domain.prompts.land import FIX_GOAL as GOAL
from taskloop.domain.prompts.land import FIX_TEXT as TEXT
from taskloop.domain.prompts.land import FIX_WHAT as WHAT


class FixerCheckpoints(Protocol):
    def save(self, *, step: str = ..., stage: int = ..., rounds: int = ..., n: int = ..., feedback: str = ...) -> None: ...


class FixerStageLoop(Protocol):
    def run(self, plan: PlanData, i: int, state: RoundState | None = ...) -> str: ...


class FixerHost(Protocol):
    """What a fix round reads of the engine: the rounds used, the plan and its cases, the repo's config, the stage loop that runs the fix,
    the checkpoint, git, its shell for the conflict-marker check, and the gate's log."""

    fixes: int
    gate_log: Path | None  # the log of the first red step, for the fix round
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
        trimmed = trim.trim_log(tail, log=str(e.gate_log or "") if kind == "gate" else "")
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
