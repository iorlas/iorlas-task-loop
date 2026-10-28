"""What a run of one bead gave the loop: run-task's outcome file (read at this one place) plus what the loop itself saw."""
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from taskloop.contracts.slots import SlotFailCode

NETWORK = "pause_network"
FAULT_SLOT = "fault_slot"


@dataclass(frozen=True)
class Verdict:
    outcome: str  # landed | failed | paused | taken | parked | ...
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
        return self.outcome == "paused" and self.kind == NETWORK

    @property
    def fault(self) -> bool:
        return self.kind.startswith("fault_")

    def quick_slot_failure(self, quick_min: float) -> bool:
        """An instant failure that is the slot's: the failures count toward setting the slot aside, not toward the stop."""
        return (self.outcome == "failed" and self.slot_fault == "slot_broken"
                and (self.pre_engine or (self.minutes is not None and self.minutes < quick_min)))

    def with_(self, **fields: Any) -> "Verdict":
        return replace(self, **fields)


def pre_engine(why: str, slot_fault: SlotFailCode | None = None) -> Verdict:
    return Verdict("failed", f"failed before the engine: {why}", pre_engine=True, slot_fault=slot_fault)


def taken(why: str) -> Verdict:
    return Verdict("taken", why)


def num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def read(path: Path, rc: int | None, log_path: Path) -> tuple[Verdict, bool]:
    """(the verdict, whether run-task gave one). No file: failed, with the exit code and where its log is."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        return Verdict("failed", f"failed: no outcome from run-task (exit {rc}); see {log_path}"), False
    rounds, tests = num(raw.get("rounds")), num(raw.get("tests_added"))
    kind = str(raw.get("kind") or "")
    return Verdict(
        outcome=str(raw.get("outcome") or "failed"), why=str(raw.get("why") or ""), kind=kind, minutes=num(raw.get("minutes")),
        rounds=None if rounds is None else int(rounds), tests_added=None if tests is None else int(tests),
        asked=bool(raw.get("asked")), run=raw.get("run"), log=raw.get("log"), retry_after=num(raw.get("retry_after")) or 0.0,
        role=str(raw.get("role") or ""), storm=str(raw.get("storm") or ""),
        slot_fault="slot_broken" if kind == FAULT_SLOT else None), True
