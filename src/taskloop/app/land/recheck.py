"""After a lost push race: revalidate the rebased inputs with the plan's checks, the barrier saved around them."""
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from taskloop.app.checks import evidence as check_evidence
from taskloop.app.land import verified
from taskloop.app.land.gate import Problem, ProblemKind
from taskloop.app.land.parts import BeginSteps, CaseChecks
from taskloop.contracts import plancheck
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.plancheck import PlanData, StageData


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
        verified.refuse(results, e)
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
