"""What a run of one bead gave the loop: run-task's outcome file (read at this one place) plus what the loop itself saw."""
from dataclasses import dataclass, replace
from os import EX_CONFIG
from pathlib import Path
from typing import Any

from taskloop.contracts import wire
from taskloop.contracts.config import ProfileReadError
from taskloop.contracts.enums import Result
from taskloop.contracts.run import RunReport
from taskloop.contracts.slots import SlotFailCode
from taskloop.domain.land.matchers import NetText

NETWORK = "pause_network"
FAULT_SLOT = "fault_slot"
PROFILE_AHEAD = "profile_ahead"


def profile_ahead(version: str, error: BaseException | None = None) -> Verdict:
    if isinstance(error, SystemExit):
        error = error.__cause__
    if isinstance(error, ProfileReadError):
        return Verdict(Result.PAUSED, str(error), kind=PROFILE_AHEAD)
    return Verdict(Result.PAUSED, "profile newer than this tl: the repo's .task-loop.json is not understood by "
                   f"tl {version}; restart the factory on the installed version", kind=PROFILE_AHEAD)


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
    fingerprint: str = ""
    pre_engine: bool = False  # the engine never started: no verdict on the bead
    slot_fault: SlotFailCode | None = None  # the slot's own git state broke, not the bead
    recovery_failed: bool = False  # a slot reset was retried before judging the slot broken

    @property
    def paused_for_network(self) -> bool:
        return self.outcome is Result.PAUSED and self.kind == NETWORK

    @property
    def fault(self) -> bool:
        return self.kind.startswith("fault_")

    def quick_slot_failure(self, quick_min: float) -> bool:
        """An instant failure that is the slot's: the failures count toward setting the slot aside, not toward the stop."""
        return (self.outcome is Result.FAILED and self.slot_fault == "slot_broken"
                and ((self.pre_engine and self.recovery_failed)
                     or (not self.pre_engine and self.minutes is not None and self.minutes < quick_min)))

    def with_(self, **fields: Any) -> Verdict:
        return replace(self, **fields)


def pre_engine(why: str, slot_fault: SlotFailCode | None = None, *, recovery_failed: bool = False) -> Verdict:
    if NetText.down(why):
        return Verdict(Result.PAUSED, f"paused before the engine: {why}", kind=NETWORK, pre_engine=True)
    if slot_fault == "slot_broken" and recovery_failed:
        return Verdict(Result.FAILED, f"failed before the engine: {why}", pre_engine=True,
                       slot_fault=slot_fault, recovery_failed=True)
    return Verdict(Result.PAUSED, f"transient before the engine: {why}", kind="transient_infrastructure", pre_engine=True,
                   slot_fault=slot_fault)


def taken(why: str) -> Verdict:
    return Verdict(Result.TAKEN, why)


def read(path: Path, rc: int | None, log_path: Path, version: str = "unknown") -> tuple[Verdict, bool]:
    """(the verdict, whether run-task gave one). No file: exit 78 pauses for the owner; other exits fail with the log path.
    A file that is not a RunReport of this version fails too, naming the file and the fault."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        if rc == EX_CONFIG:
            try:
                log = log_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                log = ""
            for line in reversed(log.splitlines()):
                diagnostic = line.removeprefix("task-loop: ")
                if (diagnostic.startswith("the repo profile ") and " is unreadable: " in diagnostic
                        and diagnostic.endswith("; fix it, the factory stays parked")):
                    return Verdict(Result.PAUSED, diagnostic, kind=PROFILE_AHEAD), False
            return profile_ahead(version), False
        return Verdict(Result.FAILED, f"failed: no outcome from run-task (exit {rc}); see {log_path}"), False
    try:
        raw: RunReport = wire.load(RunReport, text)
    except ValueError as err:  # msgspec.ValidationError, StaleRecord, bad JSON
        return Verdict(Result.FAILED, f"failed: outcome file {path} is not a RunReport v{RunReport.V}: {err}; see {log_path}"), False
    return Verdict(
        outcome=raw.outcome, why=raw.why, kind=raw.kind, minutes=raw.minutes, rounds=raw.rounds, tests_added=raw.tests_added,
        asked=raw.asked, run=raw.run, log=raw.log, retry_after=raw.retry_after or 0.0, role=raw.role, storm=raw.storm,
        fingerprint=raw.fingerprint,
        slot_fault="slot_broken" if raw.kind == FAULT_SLOT else None), True
