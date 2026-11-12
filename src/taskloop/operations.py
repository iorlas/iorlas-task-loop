"""The step commands' operations over the existing ports: start (admit, launch, or repeat a captured step through the
`Repeat` port; a done step with a following one advances to it through the `Advance` port, any other released attempt is
answered, an abandoned one admitted afresh at the first step), verify (which then releases the slot,
settled, and publishes a verified result), release (`Release`: settled or abandon) and publish (`Publish`: push the
verified commit to origin's `task/<id>`), each following a task's current attempt, whatever its step; values in, values
out. The status reads are `attempt_status`'s. Nothing here merges or lands. `result_data.as_data` is the one JSON shape
of every result.

A done implement attempt goes to the check step (tl-8bh9.14.6 sections 5, 9, 10; `check_status.route`): advanced, or
re-run after a failed checks attempt, through the `ChecksPorts` admission; an admitted checks attempt, and a racing
winner, are launched with the checks launcher, never the agent's; so is a round's relaunch (`relaunch_checks`). A task's
release goes to its latest checks attempt first; its abandon releases that, then abandons the implement attempt (whose
claim it returns). A land candidate of that checks attempt still holding its slot goes before both (tl-8bh9.14.8 section
13): released settled, or abandoned (superseded `abandoned`) unless it is pushable or delivered (`landing`, `landed`).
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Literal, Protocol

from sqlite_store import SchemaError

from taskloop.access import SANDBOX
from taskloop.admit import AdmitRequest, AdmitResult, Admitted, AdmitUnavailable
from taskloop.admit_chain import NextStepRequest
from taskloop.attempt import collect, succeeded
from taskloop.attempt_reads import PublishedRow, StoreRefused
from taskloop.attempt_store import AttemptStore, StoreUnavailable
from taskloop.attempt_types import (
    AttemptKey,
    EntryIdentity,
    NotApplicable,
    Rejected,
    Unsettled,
    Verified,
    VerifyRefused,
    VerifyResult,
    VerifyUnavailable,
)
from taskloop.check_admit import ChecksRequest
from taskloop.check_status import HALF_DONE, checks_result, latest, route
from taskloop.check_store import ChecksRow, CheckStore
from taskloop.land_store import LandRow, LandStore
from taskloop.launch import AlreadyRunning, Launched, LaunchRefused, LaunchResult, LaunchUnavailable, LaunchUncertain
from taskloop.machine_config import ConfigRefused
from taskloop.publish import BranchPublished, NotPublished, PublishResult, publish_word
from taskloop.slot_release import AlreadyReleased, NotReleased, Released, ReleaseResult, release_word
from taskloop.slots import Adopted, NotAdopted, SlotView
from taskloop.steps import CHECK, following

type Clock = Callable[[], float]
type FailureKind = Literal["refused", "unavailable", "uncertain", "rejected", "not_applicable", "unsettled", "defect"]
UNKNOWN_KINDS: Final = ("unavailable", "uncertain", "unsettled")  # re-running is safe: exit 3
UNCLAIMING: Final = "Abandoned, but the tracker claim is still to be returned: run `tl step release --abandon` again."
LATE: Final = "late_relaunch"  # the counted word of a round's relaunch of a checks attempt past its deadline
VERIFY_KINDS: Final[dict[type[Rejected | NotApplicable | VerifyRefused | Unsettled | VerifyUnavailable], FailureKind]] = {
    Rejected: "rejected",
    NotApplicable: "not_applicable",
    VerifyRefused: "refused",
    Unsettled: "unsettled",
    VerifyUnavailable: "unavailable",
}


class Admit(Protocol):
    def admit(self, request: AdmitRequest) -> AdmitResult: ...


class Advance(Protocol):
    def admit_next(self, request: NextStepRequest) -> AdmitResult: ...


class ChecksAdmit(Protocol):
    def admit_checks(self, request: ChecksRequest) -> AdmitResult: ...


class Launch(Protocol):
    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult: ...


class Verify(Protocol):
    def verify(self, key: AttemptKey) -> VerifyResult: ...


class Release(Protocol):
    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult: ...


class ChecksReleasing(Release, Protocol):
    """A checks attempt's release, and a land candidate's (`check_release.ChecksRelease`)."""

    def release_candidate(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult: ...


class Publish(Protocol):
    def publish(self, key: AttemptKey) -> PublishResult: ...


@dataclass(frozen=True)
class Failed:
    """Every refusal and unknown in one shape; `detail` is diagnostic only. `admitted`: this start admitted the attempt
    before its launch failed, so the tracker claim and the slot are held (re-running `tl step start` retries the launch).
    `checks`: a checks attempt's refusal (its words are guided by `step_guide.CHECKS_GUIDE` where they differ); `land`: a
    land candidate's (guided by `land_guide.LAND_GUIDE` first)."""

    kind: FailureKind
    reason: str
    detail: str = ""
    claim_leaked: bool = False
    slots: tuple[SlotView, ...] = ()
    admitted: bool = False
    checks: bool = False
    land: bool = False

    @property
    def word(self) -> str:
        return f"{self.kind}:{self.reason}"


class Repeat(Protocol):
    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: EntryIdentity | None, minutes: int) -> Started | Failed: ...


@dataclass(frozen=True)
class ChecksPorts:
    """The check step's start: its admission (`check_admit`) and the launcher of `taskloop.check_entry`; and the settled
    release of a concluded checks attempt whose entry is gone (`check_release.ChecksRelease`, the round's)."""

    admission: ChecksAdmit
    launcher: Launch
    release: Release


@dataclass(frozen=True)
class StartPorts:
    reader: AttemptStore
    admission: Admit
    launcher: Launch
    clock: Clock
    repeat: Repeat
    advance: Advance
    checks: ChecksPorts


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
    deadline from the given minutes. `result`: the collected outcome a repeating start found instead. `step`: the step
    the attempt belongs to (`plan`, `implement`, read back from factory.db; `check`, set by the checks route); None when
    that read failed (the start stands)."""

    status: Literal["started", "relaunched", "already_running", "already_dispatched", "repeated"]
    backlog: str
    task_id: str
    attempt_id: str
    existing: bool
    entry: EntryIdentity | None = None
    number: int | None = None
    result: str = ""
    step: str | None = None


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
    """`tl step release`: what this call changed (`released`) or that nothing was pending (`already_released`); a
    checks attempt's (`attempt_id`) or land candidate's (`candidate`) release names no claim of its own (`kept`: its
    implement attempt's)."""

    backlog: str
    task_id: str
    attempt_id: str
    result: Released | AlreadyReleased
    checks: ReleasedTask | None = None  # the abandon's first half: the latest checks attempt's release
    land: ReleasedTask | None = None  # before it: the land candidate still holding its slot
    candidate: bool = False  # `attempt_id` is a land candidate's


@dataclass(frozen=True)
class PublishedTask:
    """`tl step publish`: recorded by this call, or before (`PublishedRow`: no Git, no network)."""

    backlog: str
    task_id: str
    attempt_id: str
    result: BranchPublished | PublishedRow


@dataclass(frozen=True)
class Adoption:
    slots: tuple[Adopted | NotAdopted, ...]


type Action = Literal["start", "relaunch", "repeat", "verify", "advance", "release", "publish", "report", "skip"]


@dataclass(frozen=True)
class Move:
    """One thing a scheduling round did or saw for one task (`round`): `word` is an existing fixed word (a start's
    status, `<kind>:<reason>`, a verdict with its release and branch words, a publication, a `Next` word or a skip
    reason); `detail` is diagnostic only and never logged; `step`, the step of the move's attempt (with `attempt_id`)."""

    task_id: str
    action: Action
    word: str
    attempt_id: str = ""
    detail: str = ""
    step: str = ""


type Quiet = frozenset[tuple[str, str, str, str]]  # (task, action, word, attempt) keys already in the round log


@dataclass(frozen=True)
class Round:
    """`tl step next`: the moves in the order performed; `stopped`, the word that ended admission early; `logged`, False
    when a round-log line could not be written; `written`, the keys of its moves and of its stopped word
    (`("", "stopped", word, "moves=<n>")`) now in the round log (written now, or before and unchanged): the next round's `quiet`,
    empty when any write failed so that the next round writes the state again."""

    backlog: str
    moves: tuple[Move, ...]
    stopped: str = ""
    logged: bool = True
    written: Quiet = frozenset()


@dataclass(frozen=True)
class Ended:
    """`tl step rounds` stopped: `interrupted` (the first Ctrl-C), `abrupt` (a second Ctrl-C, the surface's) or the
    whole-round refusal that ended it (`<kind>:<reason>`); launched steps keep running in every case."""

    backlog: str
    reason: str
    detail: str = ""


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
    """`--minutes` of `tl step start`, `next` and `rounds`: from 1 to MAX_MINUTES, checked before any
    store, tracker or launch call."""
    ok = 1 <= minutes <= MAX_MINUTES
    return None if ok else Failed("refused", "choices", f"--minutes must be from 1 to {MAX_MINUTES}")


@dataclass(frozen=True)
class _Advance:
    """The task's current attempt is done (verified, released settled, published) and its step has a following one:
    `step`, whose attempt `number` is admitted next (a checks re-run's is its failed latest one's + 1)."""

    previous: AttemptKey
    step: str
    number: int = 1


@dataclass(frozen=True)
class _Relaunch:
    """The done implement attempt's admitted checks attempt `key`: launched with the checks launcher."""

    key: AttemptKey


def start(ports: StartPorts, request: StartRequest, *, advancing: str | None = None) -> Started | Failed:
    """An existing attempt is launched as admitted (no tracker read), a captured one repeated, a done one advanced to the
    next step (one tracker read, no claim), another released one answered with its result; otherwise (none, or the
    current one abandoned) admit first. A refusal or unknown stops before the launch; a concurrent start that won
    (`task_attempted`) is launched as existing. A start names its attempt's step. A done implement attempt goes to the
    check step (`_checked`): admitted (the advance, or the re-run of a failed checks attempt), launched with the checks
    launcher, refused `release` while the task's abandon is half done, or answered with its result.

    `advancing` (the round's advance): only the advance of that done attempt, never a fresh admission, relaunch or
    repeat: refused `abandoned` when the task's attempt was abandoned since, `changed` when it is no longer that done
    attempt (another current attempt, or not advanceable)."""
    found = _start(ports, request, advancing)
    if isinstance(found, Failed) or found.step is not None:
        return found
    try:
        return replace(found, step=ports.reader.step_of(found.attempt_id))
    except StoreUnavailable:
        return found


def _start(ports: StartPorts, request: StartRequest, advancing: str | None) -> Started | Failed:
    refused = minutes_refused(request.minutes)
    if refused is not None:
        return refused
    try:
        found = _current(ports, request)
        if advancing is not None and not (isinstance(found, _Advance) and found.previous.attempt_id == advancing and found.number == 1):
            found = _not_advanced(found)
        if isinstance(found, (Started, Failed)):
            return found
        if isinstance(found, (tuple, _Relaunch)):  # an existing attempt: launched as admitted
            target = (found[0] if isinstance(found, tuple) else found.key, True)
        else:
            target = _admit(ports, request, found)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if isinstance(target, Failed):
        return target
    key, existing = target
    if isinstance(found, tuple) and found[1] == "captured":  # the step ran: repeat it when its leftovers are repeatable
        return ports.repeat.repeat(request.backlog, request.task_id, key, found[2], request.minutes)
    checks = isinstance(found, _Relaunch) or (isinstance(found, _Advance) and found.step == CHECK)
    outcome = (ports.checks.launcher if checks else ports.launcher).launch(request.backlog, request.task_id, request.minutes)
    result = launched(outcome, request.backlog, request.task_id, key, existing=existing)
    result = replace(result, step=CHECK) if checks and isinstance(result, Started) else result
    return replace(result, admitted=True) if isinstance(result, Failed) and not existing else result


type _Found = tuple[AttemptKey, str, EntryIdentity | None] | _Advance | _Relaunch | Started | Failed | None


def _current(ports: StartPorts, request: StartRequest) -> _Found:
    """The task's current attempt; None when there is none or its abandon finished (a fresh attempt is admitted). An
    abandon whose claim is still `unclaiming` refuses `release` (its own unclaim could undo a fresh claim). A settled
    release whose step is done and has a following step advances; any other is the task's answer: `already_dispatched`
    with its result, never relaunched or repeated."""
    found = ports.reader.attempt_of(request.backlog, request.task_id)
    released = None if found is None else ports.reader.release_of(found[0])
    if found is None or released is None:
        return found
    if released.abandoned:
        return Failed("refused", "release", UNCLAIMING) if released.claim == "unclaiming" else None
    result = collect(ports.reader, found[0])
    rows = ports.reader.attempts(request.backlog, request.task_id) if succeeded(result) else ()
    step = following(rows[0].step) if rows and rows[0].key == found[0] and rows[0].published is not None else None
    if step is not None:
        return _Advance(found[0], step) if step != CHECK else _checked(ports, request, found[0])
    return Started("already_dispatched", request.backlog, request.task_id, found[0].attempt_id, True, result=result.reason)


def _checked(ports: StartPorts, request: StartRequest, implement: AttemptKey) -> _Found:
    """The done implement attempt's latest checks attempt (`check_status.route`): advance or re-run it, launch it, refuse
    `release` while the task's abandon is half done (never a launch), or answer its result."""
    row = latest(CheckStore(ports.reader.connect, ports.reader.begin), implement.attempt_id)
    found = route(row)
    if row is None or found == "advance":
        return _Advance(implement, CHECK)
    match found:
        case "abandoned":
            return Failed("refused", "release", HALF_DONE)
        case "launch":
            return _Relaunch(row.key)
        case "rerun":
            return _Advance(implement, CHECK, row.number + 1)
        case "answer":
            answer = checks_result(row).reason
            return Started("already_dispatched", request.backlog, request.task_id, row.key.attempt_id, True, result=answer, step=CHECK)


def relaunch_checks(ports: StartPorts, backlog: str, task_id: str, attempt_id: str, minutes: int) -> Started | Failed:
    """A round's relaunch of the snapshot's checks attempt `attempt_id` with the checks launcher, never an admission or a
    re-run: only while it is still the task's latest checks attempt (`CheckStore.attempt_of`, the launcher's own read),
    `admitted` and not released; else `refused:changed`, `abandoned`, `released` or `concluded`. Past its deadline the
    relaunch is counted first (`LATE`, one more toward `stuck:checks_refused`), so a relaunch that never reaches the
    entry's own count (a failed or uncertain launch, an entry refusing before the attempt is its own, a crash) stops after
    at most two; before the deadline such relaunches repeat each round, as an agent attempt's do until its deadline."""
    store = CheckStore(ports.reader.connect, ports.reader.begin)
    try:
        found = store.attempt_of(backlog, task_id)
        row = None if found is None else store.row(found[0])
        if found is None or row is None or found[0].attempt_id != attempt_id:
            return Failed("refused", "changed", "Another attempt is current since this round read the store")
        if found[1] != "admitted":
            return Failed("refused", "abandoned" if row.abandoned else found[1])
        if ports.clock() >= row.deadline:
            store.refused(found[0], LATE)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    except StoreRefused as error:
        return Failed("refused", error.reason, "The checks attempt no longer holds its reservation")
    result = launched(ports.checks.launcher.launch(backlog, task_id, minutes), backlog, task_id, found[0], existing=True)
    return replace(result, step=CHECK) if isinstance(result, Started) else result


def _not_advanced(found: _Found) -> Failed:
    """Why the round's advance of a done attempt does not run: the read's own refusal, its abandon, or another state."""
    if isinstance(found, Failed):
        return found
    if found is None:
        return Failed("refused", "abandoned", "The task's attempt was abandoned since this round read the store")
    return Failed("refused", "changed", "The task's current attempt is no longer the done step this round read")


def _admit(ports: StartPorts, request: StartRequest, advance: _Advance | None) -> tuple[AttemptKey, bool] | Failed:
    """The new attempt's key (a fresh admission, or the next step's after `advance`), or the winner's after
    `task_attempted`; StoreUnavailable propagates."""
    deadline = deadline_after(request.minutes, ports.clock)
    choices = (request.checkout, request.model, request.effort, SANDBOX, deadline)
    checks = advance is not None and advance.step == CHECK
    if advance is None:  # no label yet: H3 of tl-8bh9.14.9 passes the round's (`tl step start` stays None)
        admitted = ports.admission.admit(AdmitRequest(request.task_id, request.backlog, request.tracker_root, *choices, None))
    elif checks:
        admitted = ports.checks.admission.admit_checks(ChecksRequest(advance.previous, request.checkout, deadline, advance.number))
    else:
        admitted = ports.advance.admit_next(NextStepRequest(advance.previous, *choices))
    if isinstance(admitted, Admitted):
        return admitted.key, False
    if isinstance(admitted, AdmitUnavailable):
        return Failed("unavailable", admitted.what, admitted.detail, admitted.claim_leaked)
    if admitted.reason != "task_attempted":
        return Failed("refused", admitted.reason, admitted.detail, admitted.claim_leaked, admitted.slots)
    winner = CheckStore(ports.reader.connect, ports.reader.begin) if checks else ports.reader  # its launcher's own read
    found = winner.attempt_of(request.backlog, request.task_id)
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
            return Failed("uncertain", "launch", "The registered entry may run; `tl step show` observes it")


def verify_task(
    reader: AttemptStore, verifier: Verify, releaser: Release, publisher: Publish, backlog: str, task_id: str
) -> VerifiedTask | Failed:
    """A stored verdict returns with no Git read; otherwise one verification, stored once when it settles. After a
    verdict (new or stored) the slot is released, settled, and a verified result published: a held release or a failed
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


def release_task(
    reader: AttemptStore, releaser: Release, checks: ChecksReleasing, backlog: str, task_id: str, *, abandon: bool
) -> ReleasedTask | Failed:
    """`tl step release`: the task's current attempt released (settled), or abandoned (`abandon`). With a checks attempt
    (section 10) its latest one goes first (`checks`), and before it its latest land candidate while that holds its slot;
    settled, the first of them is all; an abandon then abandons the implement attempt, which returns the claim. A failure
    after the candidate's abandon (marked superseded `abandoned`) or the checks attempt's leaves `Next: release`
    (`land_status.land_next`; `tl step land` refuses `abandoning`); rerunning `--abandon` finishes it. Once the implement
    attempt's claim is no longer `kept` and its latest checks attempt is released, those halves are done and not reported
    again: the answer is the implement attempt's (its claim as it is)."""
    try:
        found = reader.attempt_of(backlog, task_id)
        row = None if found is None else latest(CheckStore(reader.connect, reader.begin), found[0].attempt_id)
        ended = None if row is None or row.released_at is None or found is None else reader.release_of(found[0])
        held = None if row is None or row.released_at is None else LandStore(reader.connect, reader.begin).latest(row.key.attempt_id)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if found is None:
        return Failed("refused", "absent", f"No attempt for {task_id} in backlog {backlog}")
    row = None if ended is not None and ended.claim != "kept" else row  # the abandon went past its checks half
    halves = _halves(checks, (backlog, task_id), row, held, abandon)
    if isinstance(halves, Failed):
        return halves
    landed, went = halves
    settled = landed or went
    if not abandon and settled is not None:
        return settled
    result = releaser.release(found[0], abandon)
    if isinstance(result, NotReleased):
        return Failed(result.kind, result.reason, result.detail + ("" if went is None else " The checks attempt was released first."))
    return ReleasedTask(backlog, task_id, found[0].attempt_id, result, went, landed)


def _halves(
    checks: ChecksReleasing, task: tuple[str, str], row: ChecksRow | None, held: LandRow | None, abandon: bool
) -> tuple[ReleasedTask | None, ReleasedTask | None] | Failed:
    """The land candidate still holding its slot first, then the checks attempt (settled, a released one changes nothing);
    each released one as its `ReleasedTask`, a refusal of either as `Failed` (the checks attempt's saying the candidate
    went first)."""
    land = None if row is None or held is None or not held.holds_slot else checks.release_candidate(held.key, abandon)
    if isinstance(land, NotReleased):
        return Failed(land.kind, land.reason, land.detail, land=True)
    landed = None if land is None or held is None else ReleasedTask(*task, held.key.attempt_id, land, candidate=True)
    first = None if row is None else checks.release(row.key, abandon)
    if isinstance(first, NotReleased):
        before = "" if landed is None else " The land candidate was released first."
        return Failed(first.kind, first.reason, first.detail + before, checks=True)
    return landed, None if row is None or first is None else ReleasedTask(*task, row.key.attempt_id, first)


def publish_task(reader: AttemptStore, publisher: Publish, backlog: str, task_id: str) -> PublishedTask | Failed:
    """`tl step publish`: the task's current attempt's verified commit pushed to origin's `task/<id>` (first try or retry)."""
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
    """An unsettled slot carries its listing (`bounded` where it was read) as the detail, as `tl step show` prints it."""
    if isinstance(result, VerifyUnavailable) and result.reason == "inconsistent":  # same inputs, another verdict: a defect
        return Failed("defect", result.reason)
    if isinstance(result, Unsettled):
        return Failed("unsettled", result.reason, "\n".join(result.listing))
    return Failed(VERIFY_KINDS[type(result)], result.what if isinstance(result, NotApplicable) else result.reason)
