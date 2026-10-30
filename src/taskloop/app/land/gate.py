"""The land gate on the rebased tree: the registry's gate steps (engine.checks with run gate or both), run through the same check
machinery a stage's round uses (Checker.run_items): groups in order, a red group skips the groups after it, a step green at its inputs on
this tree and base is skipped and logged as cached, each step has its own start and end row (seconds, exit) in the check log. A green
gate is nothing but its steps' green results in the per-check cache: the same tree is not gated twice (a push rejected and tried again, a
re-land after the network came back)."""
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from taskloop.app.checks import evidence
from taskloop.app.checks.host import CheckFault
from taskloop.app.land import verified
from taskloop.contracts import log as rec
from taskloop.contracts.checks import CheckFaultKind
from taskloop.domain.checks.specs import gate_items

FAULTS = MappingProxyType({CheckFaultKind.STALE_BASE: "FAULT_STALE_BASE", CheckFaultKind.KILLED: "PAUSE_KILLED"})


@dataclass(frozen=True)
class Problem:
    """Why a try of the land did not push: `kind` is gate, conflict or verify; `text` goes to the fix round; `named`: a gate's red steps."""

    kind: str
    text: str
    named: str = ""


class Gate:
    def __init__(self, host: Any) -> None:
        self.e = host

    def green(self) -> bool:
        """The gate already passed on exactly this tree (and base): every step is green in the cache or not due."""
        return bool(self.e.checker.gate_green())

    def run(self) -> Problem | None:
        """-> None when the gate passed (or already had on this tree), else the problem for a fix round."""
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
            return None
        e.gate_log = e.run_dir / reds[0].log if reds[0].log else None
        names = ", ".join(c.id for c in reds)
        e.steps.outcome("gate red", names)
        return Problem("gate", f"gate steps red: {names}\n" + evidence.failure_brief(reds, e.run_dir), names)
