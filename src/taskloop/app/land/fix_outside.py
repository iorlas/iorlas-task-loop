"""A red check or gate, or a conflict, is fixed outside the land lock, then the land tries again."""
from typing import Protocol

from taskloop.app.land.gate import Problem, ProblemKind
from taskloop.app.land.parts import MoveSteps, StageCheckout
from taskloop.contracts import plancheck
from taskloop.contracts.plancheck import PlanData
from taskloop.contracts.ports import Sh


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
    def sh(self) -> Sh: ...
    def git(self, *args: str) -> str: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class FixOutside:
    def __init__(self, host: FixOutsideHost) -> None:
        self.e = host

    def run(self, problem: Problem) -> None:
        e = self.e
        if e.fixes < e.cfg.max_fix_rounds:
            cause = {ProblemKind.GATE: "gate_red", ProblemKind.VERIFY: "checks_red", ProblemKind.CONFLICT: "conflict"}[problem.kind]
            first = problem.text.strip().splitlines() or [""]
            red = f"gate red on the rebased tree: {(problem.named or first[-1])[:200]}"
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
            if e.git("status", "--porcelain"):  # unlike verification before finish(), a retry check's fix follows the task commit
                e.checkout.stage_all(check=True)
                e.sh(["git", "commit", "-q", "--no-verify", "--amend", "--no-edit"], check=True, pin=True)
