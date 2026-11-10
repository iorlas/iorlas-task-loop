"""The plan commands' operations over the existing ports: start (admit and launch), status, list and verify; values in,
values out. Attempt only: nothing here prepares a task branch, publishes, releases a reservation or claim, retries an
agent or makes a second attempt for a task. `as_data` is the one JSON shape of every result; it never holds a dispatch token.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Literal, Protocol

from sqlite_store import SchemaError

from taskloop.machine_config import ConfigRefused, Loaded
from taskloop.plan import SANDBOX, collect, succeeded
from taskloop.plan_admit import AdmitRequest, AdmitResult, Admitted, AdmitUnavailable
from taskloop.plan_files import PlanFiles
from taskloop.plan_launch import AlreadyRunning, Entry, Launched, LaunchRefused, LaunchResult, LaunchUnavailable, LaunchUncertain
from taskloop.plan_store import AttemptRow, PlanStore, StoreUnavailable
from taskloop.plan_types import (
    AttemptKey,
    AttemptResult,
    NotApplicable,
    Rejected,
    Unsettled,
    Verified,
    VerifyRefused,
    VerifyResult,
    VerifyUnavailable,
)
from taskloop.slots import Adopted, NotAdopted, SlotView

type Clock = Callable[[], float]
type Seen = Literal["matching", "gone", "different_process", "unknown"]
type Observe = Callable[[Entry], Seen]  # a native process-table read of the entry's identity; no spawn or signal
type EntryState = Literal["none", "running", "gone", "different_process", "unknown"]
type Stuck = Literal["stuck:expired_admitted", "stuck:entry_lost", "stuck:hung", "stuck:unpublished", "stuck:conflict"]
type Next = Literal["start", "wait", "verify", "done", "unknown"] | Stuck
type FailureKind = Literal["refused", "unavailable", "uncertain", "rejected", "not_applicable", "unsettled", "defect"]
UNKNOWN_KINDS: Final = ("unavailable", "uncertain", "unsettled")  # re-running is safe: exit 3
VERIFY_KINDS: Final[dict[type[Rejected | NotApplicable | VerifyRefused | Unsettled | VerifyUnavailable], FailureKind]] = {
    Rejected: "rejected",
    NotApplicable: "not_applicable",
    VerifyRefused: "refused",
    Unsettled: "unsettled",
    VerifyUnavailable: "unavailable",
}


class Admit(Protocol):
    def admit(self, request: AdmitRequest) -> AdmitResult: ...


class Launch(Protocol):
    def launch(self, backlog: str, task_id: str) -> LaunchResult: ...


class Verify(Protocol):
    def verify(self, key: AttemptKey) -> VerifyResult: ...


@dataclass(frozen=True)
class Failed:
    """Every refusal and unknown in one shape; `detail` is diagnostic only. `admitted`: this start admitted the attempt
    before its launch failed, so the tracker claim and the slot are held (re-running `tl plan start` retries the launch)."""

    kind: FailureKind
    reason: str
    detail: str = ""
    claim_leaked: bool = False
    slots: tuple[SlotView, ...] = ()
    admitted: bool = False


@dataclass(frozen=True)
class Reads:
    store: PlanStore
    observe: Observe
    clock: Clock


@dataclass(frozen=True)
class Starting:
    reader: PlanStore
    admission: Admit
    launcher: Launch
    clock: Clock


@dataclass(frozen=True)
class StartRequest:
    task_id: str
    backlog: str
    tracker_root: str
    checkout: Path
    model: str
    effort: str
    minutes: int


@dataclass(frozen=True)
class Started:
    """`existing`: the attempt was admitted before; its admitted choices stand, the given ones were not applied."""

    status: Literal["started", "relaunched", "already_running", "already_dispatched"]
    backlog: str
    task_id: str
    attempt_id: str
    existing: bool
    entry: Entry | None = None


@dataclass(frozen=True)
class AttemptStatus:
    backlog: str
    task_id: str
    attempt_id: str
    slot: str
    phase: str
    entry: EntryState
    result: AttemptResult
    deadline_passed: bool
    next: Next
    entry_process: Entry | None = None  # the registered entry's identity, for the manual steps (not secret)
    worker: tuple[int, int] | None = None  # the agent's pid and process group, once registered


@dataclass(frozen=True)
class Shown:
    status: AttemptStatus
    directory: Path
    entry_log: Path


@dataclass(frozen=True)
class Listed:
    attempts: tuple[AttemptStatus, ...]


@dataclass(frozen=True)
class Checked:
    status: Literal["verified", "reused"]
    backlog: str
    task_id: str
    attempt_id: str


@dataclass(frozen=True)
class Adoption:
    slots: tuple[Adopted | NotAdopted, ...]


type Result = Started | Shown | Listed | Checked | Adoption | Loaded | Failed


def require_database(open_ro: Callable[[], sqlite3.Connection | None]) -> sqlite3.Connection | Failed:
    """Only `slot adopt` creates factory.db: every other command opens it read-only first, and refuses `database` when it
    is absent or unreadable, `schema` when it is another schema version; nothing is created."""
    try:
        con = open_ro()
    except SchemaError as error:
        return Failed("refused", "schema", str(error))
    return Failed("refused", "database", "No readable factory.db at this path; `tl slot adopt` creates it") if con is None else con


def refused_config(refused: ConfigRefused) -> Failed:
    return Failed("refused", refused.reason, refused.detail)


def deadline_after(minutes: int, clock: Clock) -> float:
    return clock() + minutes * 60


def start(ports: Starting, request: StartRequest) -> Started | Failed:
    """An existing attempt is launched as admitted (no tracker read); otherwise admit first. A refusal or unknown stops
    before the launch; a concurrent start that won (`task_attempted`) is launched as existing."""
    try:
        found = ports.reader.attempt_of(request.backlog, request.task_id)
        target = (found[0], True) if found is not None else _admit(ports, request)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if isinstance(target, Failed):
        return target
    key, existing = target
    launched = _launched(ports.launcher.launch(request.backlog, request.task_id), request, key, existing=existing)
    return replace(launched, admitted=True) if isinstance(launched, Failed) and not existing else launched


def _admit(ports: Starting, request: StartRequest) -> tuple[AttemptKey, bool] | Failed:
    """The new attempt's key, or the winner's after `task_attempted`; StoreUnavailable propagates."""
    deadline = deadline_after(request.minutes, ports.clock)
    admitted = ports.admission.admit(
        AdmitRequest(
            request.task_id, request.backlog, request.tracker_root, request.checkout, request.model, request.effort, SANDBOX, deadline
        )
    )
    if isinstance(admitted, Admitted):
        return admitted.key, False
    if isinstance(admitted, AdmitUnavailable):
        return Failed("unavailable", admitted.what, admitted.detail, admitted.claim_leaked)
    if admitted.reason != "task_attempted":
        return Failed("refused", admitted.reason, admitted.detail, admitted.claim_leaked, admitted.slots)
    found = ports.reader.attempt_of(request.backlog, request.task_id)
    return (found[0], True) if found is not None else Failed("unavailable", "store", "The winning attempt is not readable")


def _launched(result: LaunchResult, request: StartRequest, key: AttemptKey, *, existing: bool) -> Started | Failed:
    match result:
        case Launched() | AlreadyRunning():
            status = "already_running" if isinstance(result, AlreadyRunning) else "relaunched" if existing else "started"
            return Started(status, request.backlog, request.task_id, key.attempt_id, existing, result.entry)
        case LaunchRefused(reason="dispatched"):
            return Started("already_dispatched", request.backlog, request.task_id, key.attempt_id, existing)
        case LaunchRefused() | LaunchUnavailable():
            return Failed("refused" if isinstance(result, LaunchRefused) else "unavailable", result.reason)
        case LaunchUncertain():
            return Failed("uncertain", "launch", "The registered entry may run; `tl plan show` observes it")


def next_step(phase: str, entry: EntryState, result: AttemptResult, passed: bool) -> Next:
    """What a person does next, from the phase, the entry observation, the collected result and the deadline."""
    if entry == "unknown" or result.status in ("unavailable", "refused"):
        return "unknown"
    if result.status == "collected":
        return "done"
    if entry == "running":
        return "stuck:hung" if passed else "wait"
    return _stopped(phase, result, passed)


def _stopped(phase: str, result: AttemptResult, passed: bool) -> Next:
    """The entry does not run (none, gone or a different process) and nothing is collected yet."""
    if result.status == "conflict":
        return "stuck:conflict"
    if phase == "admitted":
        return "stuck:expired_admitted" if passed else "start"
    if phase in ("dispatching", "registered"):
        return "stuck:entry_lost"
    return "verify" if result.reason == "verification" else "stuck:unpublished"


def _status(reads: Reads, row: AttemptRow) -> AttemptStatus:
    entry: EntryState = "none"
    if row.entry is not None:
        seen = reads.observe(row.entry)
        entry = "running" if seen == "matching" else seen
    result = collect(reads.store, row.key)
    passed = reads.clock() >= row.deadline
    step = next_step(row.phase, entry, result, passed)
    found = (row.backlog, row.task_id, row.key.attempt_id, row.slot, row.phase)
    return AttemptStatus(*found, entry, result, passed, step, row.entry, row.worker)


def status(reads: Reads, artifacts: Path, backlog: str, task_id: str) -> Shown | Failed:
    """Read-only: creates no file or directory (the attempt directory is computed, never made)."""
    files = PlanFiles(artifacts)
    try:
        rows = reads.store.attempts(backlog, task_id)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if not rows:
        return Failed("refused", "absent", f"No attempt for {task_id} in backlog {backlog}")
    directory = files.root / files.directory(rows[0].key)
    return Shown(_status(reads, rows[0]), directory, directory / "entry.log")


def attempts_status(reads: Reads, *, stuck: bool = False) -> Listed | Failed:
    """Every attempt, or (`stuck`) only those whose next step is `stuck:*` or `unknown`."""
    try:
        rows = reads.store.attempts()
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    found = (_status(reads, row) for row in rows)
    return Listed(tuple(each for each in found if not stuck or each.next == "unknown" or each.next.startswith("stuck:")))


def verify_task(reader: PlanStore, verifier: Verify, backlog: str, task_id: str) -> Checked | Failed:
    """A stored verdict returns with no Git read; otherwise one verification, stored once when it settles."""
    try:
        found = reader.attempt_of(backlog, task_id)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if found is None:
        return Failed("refused", "absent", f"No attempt for {task_id} in backlog {backlog}")
    result = verifier.verify(found[0])
    if isinstance(result, Verified):
        return Checked("reused" if result.reused else "verified", backlog, task_id, found[0].attempt_id)
    if isinstance(result, VerifyUnavailable) and result.reason == "inconsistent":  # same inputs, another verdict: a defect
        return Failed("defect", result.reason)
    return Failed(VERIFY_KINDS[type(result)], result.what if isinstance(result, NotApplicable) else result.reason)


def exit_code(result: Result) -> int:
    """0 done or already so; 1 refused; 3 unknown, re-running is safe (2, usage, is argparse's)."""
    match result:
        case Failed(kind=kind):
            return 3 if kind in UNKNOWN_KINDS else 1
        case Adoption(slots=slots):
            reasons = {each.reason for each in slots if isinstance(each, NotAdopted)}
            return 3 if reasons & {"git_unavailable", "store_unavailable"} else 1 if reasons else 0
        case _:
            return 0


def _entry_data(entry: Entry | None) -> dict[str, object] | None:
    return None if entry is None else {"pid": entry[0], "start": entry[1], "boot": entry[2]}


def _status_data(each: AttemptStatus) -> dict[str, object]:
    return {
        "backlog": each.backlog, "task": each.task_id, "attempt_id": each.attempt_id, "slot": each.slot, "phase": each.phase,
        "entry": each.entry, "result": {"status": each.result.status, "reason": each.result.reason},
        "succeeded": succeeded(each.result), "deadline_passed": each.deadline_passed, "next": each.next,
        "entry_process": _entry_data(each.entry_process),
        "worker": None if each.worker is None else {"pid": each.worker[0], "pgid": each.worker[1]},
    }


def _slot_data(each: SlotView | Adopted | NotAdopted) -> dict[str, object]:
    match each:
        case SlotView():
            return {"name": each.name, "path": str(each.path), "state": each.state, "reason": each.reason, "attempt_id": each.attempt_id}
        case Adopted():
            return {"name": each.name, "adopted": True, "reason": None, "path": str(each.path)}
        case NotAdopted():
            return {"name": each.name, "adopted": False, "reason": each.reason, "path": None if each.path is None else str(each.path)}


def as_data(result: Result) -> dict[str, object]:
    """The one JSON shape per result (a refusal or unknown is `{"error": ...}`); no dispatch token, no version field."""
    match result:
        case Failed():
            slots = [_slot_data(each) for each in result.slots]
            error = {"kind": result.kind, "reason": result.reason, "message": result.detail, "claim_leaked": result.claim_leaked}
            return {"error": error | {"admitted": result.admitted, "slots": slots}}
        case Started():
            return {"status": result.status, "backlog": result.backlog, "task": result.task_id, "attempt_id": result.attempt_id,
                    "existing": result.existing, "entry": _entry_data(result.entry)}
        case Shown():
            return _status_data(result.status) | {"directory": str(result.directory), "entry_log": str(result.entry_log)}
        case Listed():
            return {"attempts": [_status_data(each) for each in result.attempts]}
        case Checked():
            return {"status": result.status, "backlog": result.backlog, "task": result.task_id, "attempt_id": result.attempt_id}
        case Adoption() | Loaded():
            return _setup_data(result)


def _setup_data(result: Adoption | Loaded) -> dict[str, object]:
    if isinstance(result, Adoption):
        return {"slots": [_slot_data(each) for each in result.slots]}
    settings = {
        key: {"value": each.value if isinstance(each.value, int) else str(each.value), "source": each.source}
        for key, each in result.settings.pairs()
    }
    return {"file": {"path": str(result.path), "exists": result.exists}, "settings": settings}
