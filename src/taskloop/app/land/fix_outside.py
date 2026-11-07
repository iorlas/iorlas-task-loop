"""A red check or gate, or a conflict, is fixed outside the land lock, then the land tries again."""
from types import MappingProxyType
from typing import Final, Protocol

from tlkernel import plancheck
from tlkernel.gitport import Git
from tlkernel.plancheck import PlanData

from taskloop.app.land.gate import Problem, ProblemKind
from taskloop.app.land.gitcall import must
from taskloop.app.land.host import MoveSteps, StageCheckout


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
