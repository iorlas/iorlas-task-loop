"""One engine step, no AI: the repo's checks and the stage's acceptance checks, and the stop they can end in."""
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from tlgate import evidence as check_evidence
from tlgate.domain.specs import repo_check
from tlgate.host import CheckFault, CheckStuck
from tlgate.runner import Checker
from tlkernel.checks import CheckFaultKind, CheckRun
from tlkernel.ids import CheckId
from tlkernel.kinds import Kind
from tlkernel.plancheck import StageData


class CheckStepHost(Protocol):
    @property
    def checker(self) -> Checker: ...
    @property
    def MARKERS(self) -> str: ...
    @property
    def run_dir(self) -> Path: ...

    def run_checks(self, st: StageData, name: str, acceptance_first: bool = ..., groups: Sequence[str] | None = ...,
                   conflict_fix: Sequence[str] | None = ..., **meta: object) -> CheckRun: ...
    def halt_point(self, when: bool = ..., wait: float = ...) -> None: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...
    def blocked_stuck(self, why: str, what: str, rounds: int, signature: str) -> Exception: ...
    def assert_tree(self, step: str, when: str = ...) -> None: ...


class StageChecks:
    def __init__(self, host: CheckStepHost) -> None:
        self.host = host

    @staticmethod
    def fault_kind(kind: CheckFaultKind) -> Kind:
        return {CheckFaultKind.STALE_BASE: Kind.FAULT_STALE_BASE, CheckFaultKind.DIRTY_SLOT: Kind.FAULT_SLOT,
                CheckFaultKind.KILLED: Kind.PAUSE_KILLED}[kind]

    def stoppable(self, st: StageData, name: str, acceptance_first: bool = False, groups: Sequence[str] | None = None,
                  conflict_fix: Sequence[str] | None = None, **meta: object) -> CheckRun:
        """run, then a stop (it ended a check, which reports itself failed) ends the run here."""
        run = self.host.run_checks(st, name, acceptance_first, groups, conflict_fix, **meta)
        self.host.halt_point()
        return run

    def requested(self, ids: Sequence[CheckId], name: str, **meta: object) -> CheckRun:
        """Separate informational block: same executor and evidence, no red streak or round verdict."""
        host = self.host
        host.checker.host.steps.begin("checks", f"requested checks: {name}", requested=True, **meta)
        results = []
        for cid in ids:
            spec = next(k for k in host.checker.host.cfg.checks if k.id == cid)
            try:
                run = host.checker.run_items([repo_check(spec, host.checker.host.cfg)], everything=True)
            except CheckFault as fault:
                raise host.blocked_for(fault.text, self.fault_kind(fault.kind).name) from fault
            results.extend(run.results)
            host.halt_point()
        run = CheckRun(round=host.checker.round, results=results)
        host.checker.host.checklog.round(host.checker.host.steps.id, run)
        host.checker.host.steps.outcome("requested", f"{len(results)} requested results")
        host.assert_tree("checks", "after")
        return run

    def run(self, st: StageData, name: str, acceptance_first: bool = False, groups: Sequence[str] | None = None,
            conflict_fix: Sequence[str] | None = None, **meta: object) -> CheckRun:
        """The repo's checks and the stage's acceptance checks (Checker.run). -> the round's CheckRun."""
        try:
            run = self.host.checker.run(st["checks"], name, markers=self.host.MARKERS, acceptance_first=acceptance_first, groups=groups,
                                conflict_fix=conflict_fix, **meta)
        except CheckFault as fault:
            raise self.host.blocked_for(fault.text, self.fault_kind(fault.kind).name) from fault
        except CheckStuck as stuck:
            self.host.assert_tree("checks", "after")
            brief = check_evidence.failure_brief(self.host.checker.reds(), self.host.run_dir)
            raise self.host.blocked_stuck(f"the same checks failed with the same output in {stuck.rounds} rounds in a row: "
                          "more writes will not fix them; "
                          f"it needs the owner's hint\nsignature: {stuck.signature[:400]}\n{brief}",
                          "the same red checks", stuck.rounds, stuck.signature) from stuck
        self.host.assert_tree("checks", "after")
        return run
