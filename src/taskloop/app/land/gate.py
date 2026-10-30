"""The land gate on the rebased tree: the registry's gate steps (engine.checks with run gate or both), run through the same check
machinery a stage's round uses (Checker.run_items): groups in order, a red group skips the groups after it, a step green at its inputs on
this tree and base is skipped and logged as cached, each step has its own start and end row (seconds, exit) in the check log. A green
gate is nothing but its steps' green results in the per-check cache: the same tree is not gated twice (a push rejected and tried again, a
re-land after the network came back)."""
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, final

from taskloop.app.checks import evidence
from taskloop.app.checks.host import CheckFault
from taskloop.app.land import verified
from taskloop.contracts import log as rec
from taskloop.contracts.checks import Check, CheckFaultKind, CheckRun
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.runkey import BaseSha
from taskloop.domain.checks.specs import gate_items
from taskloop.stores.runlog import RunLog

FAULTS = MappingProxyType({CheckFaultKind.STALE_BASE: "FAULT_STALE_BASE", CheckFaultKind.KILLED: "PAUSE_KILLED"})


class ProblemKind(StrEnum):
    GATE = "gate"
    CONFLICT = "conflict"
    VERIFY = "verify"
    STALE = "stale"  # main (or the tree) moved under the gate: no fix round, the lock is let go and the gate runs again


class _Seal(Enum):
    """The key to GatePass's constructor: only `mint` (below, in this module) holds it, so pyrefly refuses a GatePass built anywhere else
    (and tests/rules/test_gatepass_rule.py refuses the seal named anywhere else)."""

    ISSUED = 1


@final
@dataclass(frozen=True)
class GatePass:
    """The gate's word that `tree` passed on `base`: the push takes one and pushes only that tree on that base. Only the gate makes one."""

    tree: TreeSha
    base: BaseSha
    seal: _Seal = field(kw_only=True, repr=False, compare=False)


def mint(tree: TreeSha, base: BaseSha) -> GatePass:
    """The one factory of GatePass. Called by Gate (after its steps are green in the memo, or when the repo has no gate) and by tests."""
    return GatePass(tree, base, seal=_Seal.ISSUED)


@dataclass(frozen=True)
class Problem:
    """Why a try of the land did not push: `kind`; `text` goes to the fix round; `named`: a gate's red steps."""

    kind: ProblemKind
    text: str
    named: str = ""


class GateChecker(Protocol):
    def run_items(self, items: Sequence[Check], everything: bool = ..., learn: bool = ..., show_clean: bool = ...) -> CheckRun: ...
    def gate_green(self) -> bool: ...


class GateSteps(Protocol):
    def outcome(self, outcome: str, detail: str = ...) -> None: ...


class GateHost(Protocol):
    """What the gate reads of the engine: the repo's gate steps and the checker that runs them, git, the log and the stop point."""

    gate_log: Path | None  # the log of the first red step, for the fix round

    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def run_dir(self) -> Path: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def steps(self) -> GateSteps: ...
    @property
    def checker(self) -> GateChecker: ...
    def git(self, *args: str) -> str: ...
    def halt_point(self, when: bool = ..., wait: float = ...) -> None: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class Gate:
    def __init__(self, host: GateHost) -> None:
        self.e = host

    def green(self) -> bool:
        """The gate already passed on exactly this tree (and base): every step is green in the cache or not due."""
        return self.e.checker.gate_green()

    def passed(self) -> GatePass | None:
        """A pass for the tree and base in the worktree now: the gate is green in the memo, or the repo has no gate. Else None."""
        e = self.e
        if e.cfg.gate_checks and not self.green():
            return None
        return self.issue()

    def issue(self) -> GatePass:
        e = self.e
        return mint(TreeSha(e.git("rev-parse", "HEAD^{tree}")), BaseSha(e.git("rev-parse", e.cfg.base)))

    def run(self) -> GatePass | Problem:
        """-> the pass when the gate passed (or already had on this tree), else the problem for a fix round."""
        e = self.e
        e.gate_log = None
        tree = e.git("rev-parse", "HEAD^{tree}")
        started = time.time()
        e.log.emit(rec.GateStart(cmd=e.cfg.gate_text, log=str(e.run_dir / "checks"), tree=tree))
        try:
            run = e.checker.run_items(gate_items(e.cfg))
        except CheckFault as fault:
            e.log.emit(rec.GateEnd(exit=fault.rc, secs=round(time.time() - started)))
            raise e.blocked_for(fault.text, FAULTS[fault.kind]) from fault
        why = verified.refusal(run)
        if why:
            e.log.emit(rec.GateEnd(exit=1, secs=round(time.time() - started)))
            raise e.blocked_for(why, "FAULT_LAND")
        e.halt_point()  # a stop ended a step, which then reports itself red: the run stops here, not in a fix round
        reds = [c for c in run.results if c.red]
        skipped = not reds and all(c.cached or c.exit is None for c in run.results)
        if skipped:
            e.log.note(f"gate skipped: every step already passed on tree {tree[:12]}")
        e.log.emit(rec.GateEnd(exit=1 if reds else 0, secs=round(time.time() - started), skipped=skipped))
        if not reds:
            return self.issue()
        e.gate_log = e.run_dir / reds[0].log if reds[0].log else None
        names = ", ".join(c.id for c in reds)
        e.steps.outcome("gate red", names)
        return Problem(ProblemKind.GATE, f"gate steps red: {names}\n" + evidence.failure_brief(reds, e.run_dir), names)
