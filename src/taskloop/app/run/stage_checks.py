"""One engine step, no AI: the repo's checks and the stage's acceptance checks, and the stop they can end in."""
from collections.abc import Sequence
from typing import Any

from taskloop.app.checks import evidence as check_evidence
from taskloop.app.checks.host import CheckFault, CheckStuck
from taskloop.app.run.blocked import Blocked
from taskloop.contracts.checks import CheckFaultKind, CheckRun
from taskloop.contracts.kinds import Kind
from taskloop.contracts.plancheck import StageData
from taskloop.domain.asks import specs as askspecs


class StageChecks:
    def __init__(self, host: Any) -> None:
        self.e = host

    @staticmethod
    def fault_kind(kind: CheckFaultKind) -> Any:
        return {CheckFaultKind.STALE_BASE: Kind.FAULT_STALE_BASE, CheckFaultKind.KILLED: Kind.PAUSE_KILLED}[kind]

    def stoppable(self, st: StageData, name: str, acceptance_first: bool = False, groups: Sequence[str] | None = None,
                  conflict_fix: Sequence[str] | None = None, **meta: object) -> CheckRun:
        """run, then a stop (it ended a check, which reports itself failed) ends the run here."""
        run = self.e.run_checks(st, name, acceptance_first, groups, conflict_fix, **meta)
        self.e.halt_point()
        return run

    def run(self, st: StageData, name: str, acceptance_first: bool = False, groups: Sequence[str] | None = None,
            conflict_fix: Sequence[str] | None = None, **meta: object) -> CheckRun:
        """The repo's checks and the stage's acceptance checks (Checker.run). -> the round's CheckRun."""
        e = self.e
        try:
            run = e.checker.run(st["checks"], name, markers=e.MARKERS, acceptance_first=acceptance_first, groups=groups,
                                conflict_fix=conflict_fix, **meta)
        except CheckFault as fault:
            raise Blocked(fault.text, kind=self.fault_kind(fault.kind)) from fault
        except CheckStuck as stuck:
            e.assert_tree("checks", "after")
            brief = check_evidence.failure_brief(e.checker.reds(), e.run_dir)
            raise Blocked(f"the same checks failed with the same output in {stuck.rounds} rounds in a row: more writes will not fix them; "
                          f"it needs the owner's hint\nsignature: {stuck.signature[:400]}\n{brief}",
                          askspecs.no_progress("the same red checks", stuck.rounds, stuck.signature), kind=Kind.ASK_STUCK) from stuck
        e.assert_tree("checks", "after")
        return run
