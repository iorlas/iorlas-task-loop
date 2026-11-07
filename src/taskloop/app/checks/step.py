"""One engine step, no AI: the repo's checks and the stage's acceptance checks, and the stop they can end in."""
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from tlkernel.checks import CheckFaultKind, CheckRun
from tlkernel.kinds import Kind
from tlkernel.plancheck import StageData

from taskloop.app.checks import evidence as check_evidence
from taskloop.app.checks.host import CheckFault, CheckStuck
from taskloop.app.checks.runner import Checker
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.asks.spec import AskSpec


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
    def blocked_for(self, why: str, kind: str, stop: object = ..., spec: AskSpec | None = ...) -> Exception: ...
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
            raise self.host.blocked_for(f"the same checks failed with the same output in {stuck.rounds} rounds in a row: "
                          "more writes will not fix them; "
                          f"it needs the owner's hint\nsignature: {stuck.signature[:400]}\n{brief}",
                          Kind.ASK_STUCK.name, spec=askspecs.no_progress("the same red checks", stuck.rounds, stuck.signature)) from stuck
        self.host.assert_tree("checks", "after")
        return run
