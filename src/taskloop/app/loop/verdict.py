"""What a run of one bead gave the loop: run-task's outcome file (read at this one place) plus what the loop itself saw."""
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from taskloop.contracts import wire
from taskloop.contracts.enums import Result
from taskloop.contracts.run import RunReport
from taskloop.contracts.slots import SlotFailCode

NETWORK = "pause_network"
FAULT_SLOT = "fault_slot"


@dataclass(frozen=True)
class Verdict:
    outcome: Result
    why: str = ""
    kind: str = ""
    minutes: float | None = None
    rounds: int | None = None
    tests_added: int | None = None
    asked: bool = False
    run: str | None = None
    log: str | None = None
    run_log: str = ""
    retry_after: float = 0.0
    role: str = ""
    storm: str = ""
    pre_engine: bool = False  # the engine never started: no verdict on the bead
    slot_fault: SlotFailCode | None = None  # the slot's own git state broke, not the bead

    @property
    def paused_for_network(self) -> bool:
        return self.outcome is Result.PAUSED and self.kind == NETWORK

    @property
    def fault(self) -> bool:
        return self.kind.startswith("fault_")

    def quick_slot_failure(self, quick_min: float) -> bool:
        """An instant failure that is the slot's: the failures count toward setting the slot aside, not toward the stop."""
        return (self.outcome is Result.FAILED and self.slot_fault == "slot_broken"
                and (self.pre_engine or (self.minutes is not None and self.minutes < quick_min)))

    def with_(self, **fields: Any) -> Verdict:
        return replace(self, **fields)


def pre_engine(why: str, slot_fault: SlotFailCode | None = None) -> Verdict:
    return Verdict(Result.FAILED, f"failed before the engine: {why}", pre_engine=True, slot_fault=slot_fault)


def taken(why: str) -> Verdict:
    return Verdict(Result.TAKEN, why)


def read(path: Path, rc: int | None, log_path: Path) -> tuple[Verdict, bool]:
    """(the verdict, whether run-task gave one). No file: failed, with the exit code and where its log is. A file that is not a
    RunReport of this version (another shape, an unknown outcome) is failed too, and the verdict names the file and the fault."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return Verdict(Result.FAILED, f"failed: no outcome from run-task (exit {rc}); see {log_path}"), False
    try:
        raw: RunReport = wire.load(RunReport, text)
    except ValueError as err:  # msgspec.ValidationError, StaleRecord, bad JSON
        return Verdict(Result.FAILED, f"failed: outcome file {path} is not a RunReport v{RunReport.V}: {err}; see {log_path}"), False
    return Verdict(
        outcome=raw.outcome, why=raw.why, kind=raw.kind, minutes=raw.minutes, rounds=raw.rounds, tests_added=raw.tests_added,
        asked=raw.asked, run=raw.run, log=raw.log, retry_after=raw.retry_after or 0.0, role=raw.role, storm=raw.storm,
        slot_fault="slot_broken" if raw.kind == FAULT_SLOT else None), True
