"""The plan commands' operations over the existing ports: start (admit, launch, or repeat a captured step through the
`Repeat` port; a released attempt is answered, an abandoned one admitted afresh), status, list, verify (which then releases
the slot, settled, and publishes a verified plan), release (`Release`: settled or abandon) and publish (`Publish`: push the
verified plan commit to origin's `task/<id>`), each following a task's current attempt; values in, values out. Plan step
only: nothing here merges or lands. `result_data.as_data` is the one JSON shape of every result.
"""

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import Final, Literal, Protocol

from sqlite_store import SchemaError

from taskloop.admit import AdmitRequest, AdmitResult, Admitted, AdmitUnavailable
from taskloop.attempt import SANDBOX, collect, succeeded
from taskloop.attempt_reads import AttemptRow, PublishedRow, ReleaseRow
from taskloop.attempt_store import AttemptStore, StoreUnavailable
from taskloop.attempt_types import (
    ATTEMPTS,
    REPEATABLE,
    AttemptKey,
    AttemptResult,
    EntryIdentity,
    NotApplicable,
    Observe,
    Rejected,
    Unsettled,
    Verified,
    VerifyRefused,
    VerifyResult,
    VerifyUnavailable,
)
from taskloop.evidence_files import EvidenceFiles
from taskloop.launch import AlreadyRunning, Launched, LaunchRefused, LaunchResult, LaunchUnavailable, LaunchUncertain
from taskloop.machine_config import ConfigRefused, Loaded
from taskloop.publish import BranchPublished, NotPublished, PublishResult, publish_word
from taskloop.slot_release import AlreadyReleased, NotReleased, Released, ReleaseResult, release_word
from taskloop.slot_state import shown
from taskloop.slots import Adopted, NotAdopted, SlotView

type Clock = Callable[[], float]
type EntryState = Literal["none", "running", "gone", "different_process", "unknown"]
type Stuck = Literal["stuck:expired_admitted", "stuck:entry_lost", "stuck:hung", "stuck:unpublished", "stuck:conflict"]
type Next = Literal["start", "wait", "verify", "repeat", "repeats_exhausted", "release", "publish", "done", "unknown"] | Stuck
type Leftovers = Callable[[AttemptKey], Unsettled | None]  # read-only Git and file reads of a stage still to settle
type FailureKind = Literal["refused", "unavailable", "uncertain", "rejected", "not_applicable", "unsettled", "defect"]
UNKNOWN_KINDS: Final = ("unavailable", "uncertain", "unsettled")  # re-running is safe: exit 3
ENTRY_STATUS: Final = frozenset({"refused", "unavailable", "pending", "collected", "conflict", "failed"})
ENTRY_WORDS: Final = 8  # at most: status, reason, publish=, then=, verify=, claim=, release=, branch= (attempt_entry)
WORD: Final = re.compile(r"(?:[a-z]+=)?[A-Za-z0-9_]{1,60}(?::[A-Za-z0-9_]{1,60}){0,2}")
UNCLAIMING: Final = "Abandoned, but the tracker claim is still to be returned: run `tl plan release --abandon` again."
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
    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult: ...


class Verify(Protocol):
    def verify(self, key: AttemptKey) -> VerifyResult: ...


class Release(Protocol):
    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult: ...


class Publish(Protocol):
    def publish(self, key: AttemptKey) -> PublishResult: ...


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


class Repeat(Protocol):
    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: EntryIdentity | None, minutes: int) -> Started | Failed: ...


@dataclass(frozen=True)
class StatusPorts:
    store: AttemptStore
    observe: Observe
    clock: Clock
    leftovers: Leftovers
    boot: Callable[[], str | None]  # this machine's boot id, None when unknown (then no attempt counts as rebooted)


@dataclass(frozen=True)
class StartPorts:
    reader: AttemptStore
    admission: Admit
    launcher: Launch
    clock: Clock
    repeat: Repeat


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
    """`existing`: the attempt was admitted before; its admitted choices stand, the given ones were not applied.
    `repeated`: the step's next attempt (`number`) was admitted and launched with the previous attempt's choices and a
    deadline from the given minutes. `result`: the collected outcome a repeating start found instead."""

    status: Literal["started", "relaunched", "already_running", "already_dispatched", "repeated"]
    backlog: str
    task_id: str
    attempt_id: str
    existing: bool
    entry: EntryIdentity | None = None
    number: int | None = None
    result: str = ""


@dataclass(frozen=True)
class AttemptView:
    backlog: str
    task_id: str
    attempt_id: str
    slot: str
    phase: str
    entry: EntryState
    result: AttemptResult
    deadline_passed: bool
    next: Next
    entry_process: EntryIdentity | None = None  # the registered entry's identity, for the manual steps (not secret)
    worker: tuple[int, int] | None = None  # the agent's last known pid and process group, once registered
    leftovers: tuple[str, ...] = ()  # with `repeat`: why (REPEATABLE) and the listing, read now, never stored
    number: int = 1  # in its step; at most ATTEMPTS
    previous_attempt_id: str | None = None  # the attempt this one repeats
    repeat_reason: str | None = None
    earlier: tuple[tuple[str, str], ...] = ()  # each earlier attempt, newest first: its repeat reason, or `abandoned`
    last_entry: str | None = None  # the entry log's last line of fixed words (`refused slot_staged ...`), read now
    seq: int = 1  # the attempt's order among its task's attempts
    release: ReleaseRow | None = None  # how it ended its reservation, once released
    published: PublishedRow | None = None  # its verified commit on origin's task/<id>, once published


@dataclass(frozen=True)
class Shown:
    status: AttemptView
    directory: Path
    entry_log: Path


@dataclass(frozen=True)
class Listed:
    attempts: tuple[AttemptView, ...]


@dataclass(frozen=True)
class VerifiedTask:
    """`release`: the settled release that followed the verdict (`released`, `held:<word>`, `unavailable:<word>`);
    `published`: the publication that followed it (`published`, `refused:<word>`, `unavailable:<word>`)."""

    status: Literal["verified", "reused"]
    backlog: str
    task_id: str
    attempt_id: str
    release: str = ""
    published: str = ""


@dataclass(frozen=True)
class ReleasedTask:
    """`tl plan release`: what this call changed (`released`) or that nothing was pending (`already_released`)."""

    backlog: str
    task_id: str
    attempt_id: str
    result: Released | AlreadyReleased


@dataclass(frozen=True)
class PublishedTask:
    """`tl plan publish`: recorded by this call, or before (`PublishedRow`: no Git, no network)."""

    backlog: str
    task_id: str
    attempt_id: str
    result: BranchPublished | PublishedRow


@dataclass(frozen=True)
class Adoption:
    slots: tuple[Adopted | NotAdopted, ...]


type Action = Literal["start", "relaunch", "repeat", "verify", "publish", "report", "skip"]


@dataclass(frozen=True)
class Move:
    """One thing a scheduling round did or saw for one task (`round`): `word` is an existing fixed word (a start's
    status, `<kind>:<reason>`, a verdict with its release and branch words, a publication, a `Next` word or a skip
    reason); `detail` is diagnostic only and never logged."""

    task_id: str
    action: Action
    word: str
    attempt_id: str = ""
    detail: str = ""


type Quiet = frozenset[tuple[str, str, str, str]]  # (task, action, word, attempt) keys already in the round log


@dataclass(frozen=True)
class Round:
    """`tl plan next`: the moves in the order performed; `stopped`, the word that ended admission early; `logged`, False
    when a round-log line could not be written; `written`, the keys of its moves and of its stopped word
    (`("", "stopped", word, "")`) now in the round log (written now, or before and unchanged): the next round's `quiet`,
    empty when any write failed so that the next round writes the state again."""

    backlog: str
    moves: tuple[Move, ...]
    stopped: str = ""
    logged: bool = True
    written: Quiet = frozenset()


@dataclass(frozen=True)
class Ended:
    """`tl plan rounds` stopped: `interrupted` (the first Ctrl-C), `abrupt` (a second Ctrl-C, the surface's) or the
    whole-round refusal that ended it (`<kind>:<reason>`); launched steps keep running in every case."""

    backlog: str
    reason: str
    detail: str = ""


UNKNOWN_WORDS: Final = tuple(kind + ":" for kind in UNKNOWN_KINDS)
ABRUPT: Final = 130  # 128 + SIGINT: the shell's convention for an interrupted command


def _round_exit(result: Round) -> int:
    """3 when admission stopped on an unknown or a move's word is one, a verify's `branch=` word included, as a publish
    move's (rerunning is safe); 1 when the round's own inputs were refused; else 0 (a per-task refusal, a held release
    and a leaked claim, reported as its own move, do not change the exit)."""
    words = [result.stopped, *(word.removeprefix("branch=") for move in result.moves for word in move.word.split(" "))]
    if any(word.startswith(UNKNOWN_WORDS) or word == "unknown" for word in words):
        return 3
    return 1 if result.stopped.startswith("refused:") else 0


type Result = Started | Shown | Listed | VerifiedTask | ReleasedTask | PublishedTask | Adoption | Loaded | Round | Ended | Failed


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


MAX_MINUTES = 7 * 24 * 60  # a week: an attempt's deadline (and a renewal after a reboot) from now, at most


def minutes_refused(minutes: int) -> Failed | None:
    """`--minutes` of `tl plan start`, `next` and `rounds`: from 1 to MAX_MINUTES, checked before any
    store, tracker or launch call."""
    ok = 1 <= minutes <= MAX_MINUTES
    return None if ok else Failed("refused", "choices", f"--minutes must be from 1 to {MAX_MINUTES}")


def start(ports: StartPorts, request: StartRequest) -> Started | Failed:
    """An existing attempt is launched as admitted (no tracker read), a captured one repeated, a released one answered
    with its result; otherwise (none, or the current one abandoned) admit first. A refusal or unknown stops before the
    launch; a concurrent start that won (`task_attempted`) is launched as existing."""
    refused = minutes_refused(request.minutes)
    if refused is not None:
        return refused
    try:
        found = _current(ports, request)
        if isinstance(found, (Started, Failed)):
            return found
        target = (found[0], True) if found is not None else _admit(ports, request)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if isinstance(target, Failed):
        return target
    key, existing = target
    if found is not None and found[1] == "captured":  # the step ran: repeat it when its leftovers are repeatable
        return ports.repeat.repeat(request.backlog, request.task_id, key, found[2], request.minutes)
    outcome = ports.launcher.launch(request.backlog, request.task_id, request.minutes)
    result = launched(outcome, request.backlog, request.task_id, key, existing=existing)
    return replace(result, admitted=True) if isinstance(result, Failed) and not existing else result


def _current(ports: StartPorts, request: StartRequest) -> tuple[AttemptKey, str, EntryIdentity | None] | Started | Failed | None:
    """The task's current attempt; None when there is none or its abandon finished (a fresh attempt is admitted). An
    abandon whose claim is still `unclaiming` refuses `release` (its own unclaim could undo a fresh claim). A settled
    release is the task's answer: `already_dispatched` with its result, never relaunched or repeated."""
    found = ports.reader.attempt_of(request.backlog, request.task_id)
    released = None if found is None else ports.reader.release_of(found[0])
    if found is None or released is None:
        return found
    if released.abandoned:
        return Failed("refused", "release", UNCLAIMING) if released.claim == "unclaiming" else None
    result = collect(ports.reader, found[0])
    return Started("already_dispatched", request.backlog, request.task_id, found[0].attempt_id, True, result=result.reason)


def _admit(ports: StartPorts, request: StartRequest) -> tuple[AttemptKey, bool] | Failed:
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


def launched(result: LaunchResult, backlog: str, task_id: str, key: AttemptKey, *, existing: bool) -> Started | Failed:
    match result:
        case Launched() | AlreadyRunning():
            status = "already_running" if isinstance(result, AlreadyRunning) else "relaunched" if existing else "started"
            return Started(status, backlog, task_id, key.attempt_id, existing, result.entry)
        case LaunchRefused(reason="dispatched"):
            return Started("already_dispatched", backlog, task_id, key.attempt_id, existing)
        case LaunchRefused() | LaunchUnavailable():
            return Failed("refused" if isinstance(result, LaunchRefused) else "unavailable", result.reason)
        case LaunchUncertain():
            return Failed("uncertain", "launch", "The registered entry may run; `tl plan show` observes it")


def next_action(phase: str, entry: EntryState, result: AttemptResult, expired: bool, *, rebooted: bool = False) -> Next:
    """What a person does next, from the phase, the entry observation, the collected result and the deadline.
    `rebooted`: the registered entry is from another boot, so its relaunch renews the deadline (`register_entry`)."""
    if entry == "unknown" or result.status in ("unavailable", "refused"):
        return "unknown"
    if result.status == "collected":
        return "done"
    if entry == "running":
        return "stuck:hung" if expired else "wait"
    return _stopped(phase, result, expired and not rebooted)


def _stopped(phase: str, result: AttemptResult, expired: bool) -> Next:
    """The entry does not run (none, gone or a different process) and nothing is collected yet."""
    if result.status == "conflict":
        return "stuck:conflict"
    if phase == "admitted":
        return "stuck:expired_admitted" if expired else "start"
    if phase in ("dispatching", "registered"):
        return "stuck:entry_lost"
    return "verify" if result.reason == "verification" else "stuck:unpublished"


def _status(reads: StatusPorts, row: AttemptRow, *, probe: bool = True) -> AttemptView:
    """A task's current attempt. `probe`: read the leftovers of a stage still to settle (Git and slot reads); never for
    a listing that keeps only stuck or unknown attempts, which a `verify`, `repeat` or `repeats_exhausted` step never is."""
    entry: EntryState = "none"
    if row.entry is not None:
        seen = reads.observe(row.entry)
        entry = "running" if seen == "matching" else seen
    result = collect(reads.store, row.key)
    expired = reads.clock() >= row.deadline
    rebooted = row.entry is not None and reads.boot() not in (None, row.entry[2])
    step = _released(row, next_action(row.phase, entry, result, expired, rebooted=rebooted), succeeded(result))
    found = (row.backlog, row.task_id, row.key.attempt_id, row.slot, row.phase)
    left = reads.leftovers(row.key) if probe and step == "verify" else None
    chain = (row.number, row.previous_attempt_id, row.repeat_reason)
    ended = {"seq": row.seq, "release": row.release, "published": row.published}
    if left is None or left.reason not in REPEATABLE:
        return AttemptView(*found, entry, result, expired, step, row.entry, row.worker, (), *chain, **ended)
    step = "repeats_exhausted" if row.number >= ATTEMPTS else "repeat"
    held = AttemptResult("pending", step, result.execution)
    return AttemptView(*found, entry, held, expired, step, row.entry, row.worker, (left.reason, *left.listing), *chain, **ended)


def _released(row: AttemptRow, step: Next, verified: bool) -> Next:
    """A released attempt is `start` again (abandoned), `publish` (settled, verified, not yet on origin) or `done`; a
    collected one still holding its slot is `release` first (the entry or a verify left it held: the slot was not clean)."""
    if row.release is not None and row.release.claim == "unclaiming":
        return "release"  # the abandon's claim is still to be returned
    if row.release is not None:
        return "start" if row.release.abandoned else "publish" if verified and row.published is None else "done"
    return "release" if step == "done" and row.held else step


def show_attempt(reads: StatusPorts, artifacts: Path, backlog: str, task_id: str) -> Shown | Failed:
    """The task's current attempt; each earlier one, newest first, was repeated (superseded and fenced: nothing of it is
    collected or read) or abandoned. Read-only: creates no file or directory (the attempt directory is computed, never made)."""
    files = EvidenceFiles(artifacts)
    try:
        rows = reads.store.attempts(backlog, task_id)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if not rows:
        return Failed("refused", "absent", f"No attempt for {task_id} in backlog {backlog}")
    directory = files.root / files.directory(rows[0].key)
    earlier = tuple((older.key.attempt_id, _ended(newer, older)) for newer, older in pairwise(rows))
    last = last_entry(files.entry_tail(rows[0].key))
    return Shown(replace(_status(reads, rows[0]), earlier=earlier, last_entry=last), directory, directory / "entry.log")


def _ended(newer: AttemptRow, older: AttemptRow) -> str:
    """Why `older` is not current: `abandoned`, or the reason `newer` repeated it."""
    return "abandoned" if older.release is not None and older.release.abandoned else newer.repeat_reason or ""


def last_entry(tail: str | None) -> str | None:
    """The last line of the entry log made only of the entry's fixed words (its status word, then `reason`, `key=value`
    or `a:b` words of letters, digits and `_`), at most ENTRY_WORDS words; anything else in the log is never printed."""
    for line in reversed((tail or "").splitlines()[-20:]):
        words = line.split(" ")
        if words[0] in ENTRY_STATUS and len(words) <= ENTRY_WORDS and all(WORD.fullmatch(word) for word in words[1:]):
            return shown(line)
    return None


def list_attempts(reads: StatusPorts, *, stuck: bool = False) -> Listed | Failed:
    """Every task's current attempt (one row per task: its highest `seq`), or (`stuck`) only those whose next action is
    `stuck:*` or `unknown`."""
    try:
        every = reads.store.attempts()
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    rows = [row for before, row in zip((None, *every), every, strict=False) if before is None or before.task_id != row.task_id
            or before.backlog != row.backlog]
    found = (_status(reads, row, probe=not stuck) for row in rows)
    return Listed(tuple(each for each in found if not stuck or each.next == "unknown" or each.next.startswith("stuck:")))


def verify_task(
    reader: AttemptStore, verifier: Verify, releaser: Release, publisher: Publish, backlog: str, task_id: str
) -> VerifiedTask | Failed:
    """A stored verdict returns with no Git read; otherwise one verification, stored once when it settles. After a
    verdict (new or stored) the slot is released, settled, and a verified plan published: a held release or a failed
    publication does not change the result, its word says so."""
    try:
        found = reader.attempt_of(backlog, task_id)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if found is None:
        return Failed("refused", "absent", f"No attempt for {task_id} in backlog {backlog}")
    result = verifier.verify(found[0])
    if not isinstance(result, (Verified, Rejected)):
        return verify_failure(result)
    released = release_word(releaser.release(found[0], False))
    if isinstance(result, Rejected):
        return replace(verify_failure(result), detail=f"Release: {released}")
    published = publish_word(publisher.publish(found[0]))
    return VerifiedTask("reused" if result.reused else "verified", backlog, task_id, found[0].attempt_id, released, published)


def release_task(reader: AttemptStore, releaser: Release, backlog: str, task_id: str, *, abandon: bool) -> ReleasedTask | Failed:
    """`tl plan release`: the task's current attempt released (settled), or abandoned (`abandon`)."""
    try:
        found = reader.attempt_of(backlog, task_id)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if found is None:
        return Failed("refused", "absent", f"No attempt for {task_id} in backlog {backlog}")
    result = releaser.release(found[0], abandon)
    if isinstance(result, NotReleased):
        return Failed(result.kind, result.reason, result.detail)
    return ReleasedTask(backlog, task_id, found[0].attempt_id, result)


def publish_task(reader: AttemptStore, publisher: Publish, backlog: str, task_id: str) -> PublishedTask | Failed:
    """`tl plan publish`: the task's current attempt's verified commit pushed to origin's `task/<id>` (first try or retry)."""
    try:
        found = reader.attempt_of(backlog, task_id)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if found is None:
        return Failed("refused", "absent", f"No attempt for {task_id} in backlog {backlog}")
    result = publisher.publish(found[0])
    if isinstance(result, NotPublished):
        return Failed(result.kind, result.reason, result.detail)
    return PublishedTask(backlog, task_id, found[0].attempt_id, result)


def verify_failure(result: Rejected | NotApplicable | VerifyRefused | Unsettled | VerifyUnavailable) -> Failed:
    """An unsettled slot carries its listing (`bounded` where it was read) as the detail, as `tl plan show` prints it."""
    if isinstance(result, VerifyUnavailable) and result.reason == "inconsistent":  # same inputs, another verdict: a defect
        return Failed("defect", result.reason)
    if isinstance(result, Unsettled):
        return Failed("unsettled", result.reason, "\n".join(result.listing))
    return Failed(VERIFY_KINDS[type(result)], result.what if isinstance(result, NotApplicable) else result.reason)


def exit_code(result: Result) -> int:
    """0 done or already so (a graceful rounds stop too); 1 refused; 3 unknown, re-running is safe; 130 an abrupt rounds
    stop (2, usage, is argparse's). Rounds never end 3: they rerun by themselves."""
    match result:
        case Failed(kind=kind):
            return 3 if kind in UNKNOWN_KINDS else 1
        case Adoption(slots=slots):
            reasons = {each.reason for each in slots if isinstance(each, NotAdopted)}
            return 3 if reasons & {"git_unavailable", "store_unavailable"} else 1 if reasons else 0
        case Round():
            return _round_exit(result)
        case Ended(reason=reason):
            return 0 if reason == "interrupted" else ABRUPT if reason == "abrupt" else 1
        case _:
            return 0
