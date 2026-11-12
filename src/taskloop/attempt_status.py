"""Every step command's status read (`tl step show`, `tl step list` and the round's snapshot): a task's current attempt
with its entry observation, collected result, deadline and the `Next` word a person acts on. Read-only: values in,
values out; `result_data.as_data` is the one JSON shape.

A task whose current attempt is a done implement attempt with checks attempts shows its latest checks attempt (section 9
of tl-8bh9.14.6): the view's step, attempt, slot, phase, entry, result, deadline, `Next`, number, last entry and release are
then that checks attempt's (`check_status`); the backlog, task, order and publication stay the implement attempt's."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from itertools import pairwise
from pathlib import Path
from typing import Literal

from stream_proc import OwnedProcess

from taskloop.attempt_reads import AttemptRow, PublishedRow, ReleaseRow, StoreUnavailable
from taskloop.attempt_result import collect, succeeded
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import ATTEMPTS, REPEATABLE, AttemptKey, AttemptResult, EntryIdentity, Observe, Unsettled
from taskloop.check_status import ChecksView, checks_next, checks_release, checks_result, commands_seen
from taskloop.check_store import ChecksRow, CheckStore, ResultRow
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold_status import cause, hold_next
from taskloop.hold_store import HoldRow, HoldStore
from taskloop.land_status import LandView, land_next, land_view, with_logs
from taskloop.operations import Clock, Failed
from taskloop.setup_store import SETUP_RUNS, ProcessSeen, SetupRow, SetupSeen, SetupStore
from taskloop.steps import CHECK, following

type EntryState = Literal["none", "running", "gone", "different_process", "unknown"]
type Stuck = Literal[
    "stuck:expired_admitted", "stuck:entry_lost", "stuck:hung", "stuck:uncollected", "stuck:conflict", "stuck:setup_failed",
    "stuck:checks_refused",
]
type Next = (
    Literal["start", "wait", "verify", "repeat", "repeats_exhausted", "release", "publish", "advance", "done", "unknown", "land",
            "landed", "hold", "on_hold"]
    | Stuck
)
type Leftovers = Callable[[AttemptKey], Unsettled | None]  # read-only Git and file reads of a step still to settle


@dataclass(frozen=True)
class StatusPorts:
    store: AttemptStore
    observe: Observe
    clock: Clock
    leftovers: Leftovers
    boot: Callable[[], str | None]  # this machine's boot id, None when unknown (then no attempt counts as rebooted)
    commands: SetupSeen = lambda _process: "gone"  # a checks attempt's registered commands (the CLI: `setup_seen`)
    last_command: Callable[[AttemptKey], float | Literal["none", "unreadable"]] = lambda _key: "none"  # wall time of its latest command


@dataclass(frozen=True)
class AttemptView:
    backlog: str
    task_id: str
    step: str  # the step the attempt belongs to (`plan`, `implement`, `check`)
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
    earlier: tuple[tuple[str, str], ...] = ()  # each earlier attempt, newest first: its repeat reason, `abandoned`, `advanced`
    # or `re-run` (an earlier checks attempt of the same implement attempt)
    last_entry: str | None = None  # the entry log's last line of fixed words (`refused slot_staged ...`), read now
    seq: int = 1  # the attempt's order among its task's attempts
    release: ReleaseRow | None = None  # how it ended its reservation, once released
    published: PublishedRow | None = None  # its verified commit on origin's task/<id>, once published
    checks: ChecksView | None = None  # the latest checks attempt whose fields these are (section 9), None for an agent attempt
    land: LandView | None = None  # its latest land candidate (tl-8bh9.14.8 section 14), None before the first
    label: str | None = None  # the approval label the round took the task under (`attempt.label`); None: started by hand
    hold: HoldRow | None = None  # the hold of its agent attempt (a checks view's: of the implement attempt it follows)
    last_command: int | Literal["none", "unreadable"] | None = None  # seconds since the agent's latest command (display only);
    # `none`: no command noted yet, `unreadable`: the evidence is; None unless the agent can be running (entry `running`)
    hold_due: str | None = None  # `Next: hold` with no hold recorded yet: the reason the next round holds it for


@dataclass(frozen=True)
class SetupShown:
    """The latest setup run (`setup_store`) of the step's attempt 1, the one whose slot environment the shown attempt uses
    (a repeat runs none and keeps it), and where its log is; nothing reads the log. `attempt_id`: that attempt, when it
    is not the shown one."""

    row: SetupRow
    log: Path
    attempt_id: str | None = None


@dataclass(frozen=True)
class Shown:
    view: AttemptView
    directory: Path
    entry_log: Path
    setup: SetupShown | None = None  # None: no setup ran for the step (a plan attempt, or implement before its preparation)
    failed: ChecksView | None = None  # the unpassed results (with their logs) of the checks attempt that caused the view's hold


@dataclass(frozen=True)
class Listed:
    attempts: tuple[AttemptView, ...]


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
    return "verify" if result.reason == "verification" else "stuck:uncollected"


def _observed(reads: StatusPorts, entry: EntryIdentity | None) -> EntryState:
    if entry is None:
        return "none"
    seen = reads.observe(entry)
    return "running" if seen == "matching" else seen


def _show(reads: StatusPorts, row: AttemptRow, *, probe: bool = True) -> AttemptView:
    """A task's current attempt, or (a done implement attempt with checks attempts) its latest checks attempt; a failed
    read of those is `unknown`. `probe`: read the leftovers of a step still to settle (Git and slot reads); never for a
    listing that keeps only stuck or unknown attempts, which a `verify`, `repeat` or `repeats_exhausted` step never is,
    unless a round took it (a labelled attempt may be a due `repeats_exhausted` hold, tl-8bh9.14.9 section 3)."""
    view = _agent(reads, row, probe=probe)
    if view.next != "advance" or following(row.step) != CHECK:
        return view
    try:
        store = CheckStore(reads.store.connect, reads.store.begin)
        rows = store.of_attempt(row.key.attempt_id)
        results = store.results(rows[-1].key) if rows else ()
        setup = SetupStore(reads.store.connect, reads.store.begin).latest(rows[-1].key) if rows else None
        land = land_view(reads.store, rows[-1], reads.observe) if rows else None
    except StoreUnavailable:
        return replace(view, next="unknown")
    return _swapped(reads, view, rows, results, None if setup is None else setup.unsettled, land) if rows else view


def _swapped(
    reads: StatusPorts, view: AttemptView, rows: tuple[ChecksRow, ...], results: tuple[ResultRow, ...], setup: OwnedProcess | None,
    land: LandView | None = None,
) -> AttemptView:
    """Section 9's field swap: the latest checks attempt's fields; each earlier one `re-run`, then the implement attempt
    `advanced`, newest first. No worker, leftovers or repeat: a checks attempt has no agent. Its registered commands are
    observed only for an admitted attempt whose entry does not run (`checks_next`). A released one's `done` goes on to
    its land (`land_status.land_next`)."""
    latest, claim = rows[-1], "kept" if view.release is None else view.release.claim
    entry, expired = _observed(reads, latest.entry), reads.clock() >= latest.deadline
    stopped = latest.phase == "admitted" and latest.released_at is None and entry not in ("running", "unknown")
    commands: ProcessSeen = commands_seen(reads.commands, setup, results) if stopped else "gone"
    earlier = (*((each.key.attempt_id, "re-run") for each in reversed(rows[:-1])), (view.attempt_id, "advanced"))
    return replace(
        view, step=CHECK, attempt_id=latest.key.attempt_id, slot=latest.slot, phase=latest.phase, entry=entry,
        result=checks_result(latest), deadline_passed=expired, next=land_next(checks_next(latest, entry, expired, commands), latest, land),
        entry_process=latest.entry,
        worker=None, last_command=None, leftovers=(), number=latest.number, previous_attempt_id=None, repeat_reason=None, earlier=earlier,
        release=checks_release(latest, claim), checks=ChecksView(latest, results), land=land,
    )


def _agent(reads: StatusPorts, row: AttemptRow, *, probe: bool) -> AttemptView:
    entry = _observed(reads, row.entry)
    result = collect(reads.store, row.key)
    expired = reads.clock() >= row.deadline
    rebooted = row.entry is not None and reads.boot() not in (None, row.entry[2])
    next_word = _released(row, next_action(row.phase, entry, result, expired, rebooted=rebooted), succeeded(result))
    next_word = _setup_failed(reads, row, next_word)
    found = (row.backlog, row.task_id, row.step, row.key.attempt_id, row.slot, row.phase)
    left = reads.leftovers(row.key) if probe and next_word == "verify" else None
    chain = (row.number, row.previous_attempt_id, row.repeat_reason)
    ended = {"seq": row.seq, "release": row.release, "published": row.published, "label": row.label,
             "last_command": _idle(reads, row.key) if entry == "running" else None}
    if left is None or left.reason not in REPEATABLE:
        return AttemptView(*found, entry, result, expired, next_word, row.entry, row.worker, (), *chain, **ended)
    next_word = "repeats_exhausted" if row.number >= ATTEMPTS else "repeat"
    held = AttemptResult("pending", next_word, result.execution)
    return AttemptView(*found, entry, held, expired, next_word, row.entry, row.worker, (left.reason, *left.listing), *chain, **ended)


def _idle(reads: StatusPorts, key: AttemptKey) -> int | Literal["none", "unreadable"]:
    at = reads.last_command(key)
    return at if isinstance(at, str) else max(0, int(reads.clock() - at))


def _setup_failed(reads: StatusPorts, row: AttemptRow, step: Next) -> Next:
    """An admitted attempt 1 whose setup failed `SETUP_RUNS` times is `stuck:setup_failed`, not `start`: a relaunch
    would only refuse `environment:failed` (a repeat runs no setup). An unreadable count is `unknown`."""
    if step != "start" or row.number != 1 or row.release is not None:
        return step
    try:
        failed = SetupStore(reads.store.connect, reads.store.begin).failures(row.key)
    except StoreUnavailable:
        return "unknown"
    return "stuck:setup_failed" if failed >= SETUP_RUNS else step


def _released(row: AttemptRow, step: Next, verified: bool) -> Next:
    """A released attempt is `start` again (abandoned), `publish` (settled, verified, not yet on origin: never advanced
    past), `advance` (settled, verified and published, and its step has a following one) or `done`; a collected one still
    holding its slot is `release` first (the entry or a verify left it held: the slot was not clean)."""
    if row.release is not None and row.release.claim == "unclaiming":
        return "release"  # the abandon's claim is still to be returned
    if row.release is not None and row.release.abandoned:
        return "start"
    if row.release is not None and verified:
        return "publish" if row.published is None else "advance" if following(row.step) is not None else "done"
    if row.release is not None:
        return "done"
    return "release" if step == "done" and row.held else step


def show_attempt(reads: StatusPorts, artifacts: Path, backlog: str, task_id: str) -> Shown | Failed:
    """The task's current attempt; each earlier one, newest first, was repeated (superseded and fenced: nothing of it is
    collected or read), abandoned, or advanced (done: the next step followed it). Read-only: creates no file or
    directory (the attempt directory is computed, never made)."""
    files = EvidenceFiles(artifacts)
    try:
        rows = reads.store.attempts(backlog, task_id)
        first = _first(rows) if rows else None
        latest = None if first is None else SetupStore(reads.store.connect, reads.store.begin).latest(first.key)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    if not rows:
        return Failed("refused", "absent", f"No attempt for {task_id} in backlog {backlog}")
    directory = files.root / files.directory(rows[0].key)
    earlier = tuple((older.key.attempt_id, _ended(newer, older)) for newer, older in pairwise(rows))
    view = _holding(reads, (_show(reads, rows[0]),))[0]
    if view.checks is not None:
        try:
            return _checks_shown(reads, files, replace(view, earlier=view.earlier + earlier), view.checks)
        except StoreUnavailable as error:
            return Failed("unavailable", "store", str(error))
    setup = None
    if first is not None and latest is not None:
        other = None if first is rows[0] else first.key.attempt_id
        setup = SetupShown(latest, files.root / files.directory(first.key) / f"setup-{latest.run}.log", other)
    shown = replace(view, earlier=earlier, last_entry=files.last_entry(rows[0].key))
    try:
        failed = _failed_checks(reads, files, view.hold)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    return Shown(shown, directory, directory / "entry.log", setup, failed)


def _failed_checks(reads: StatusPorts, files: EvidenceFiles, hold: HoldRow | None) -> ChecksView | None:
    """A hold caused by a checks attempt (`cause_id` is not the agent attempt): that attempt's unpassed results of its latest
    block with their log paths, from factory.db and the attempt's own directory, never from the tracker comment or a log."""
    if hold is None or hold.cause_id == hold.attempt_id:
        return None
    store = CheckStore(reads.store.connect, reads.store.begin)
    row = next((each for each in store.of_attempt(hold.attempt_id) if each.key.attempt_id == hold.cause_id), None)
    if row is None:
        return None
    results = tuple(each for each in store.results(row.key) if each.conclusion != "passed")
    logs = tuple(None if each.conclusion == "undefined" else files.check_path(row.key, each.block, each.name) for each in results)
    return ChecksView(row, results, logs)


def _checks_shown(reads: StatusPorts, files: EvidenceFiles, view: AttemptView, checks: ChecksView) -> Shown:
    """The checks attempt's own directory, entry log, latest setup run and each latest-block result's log (computed,
    never made); StoreUnavailable propagates."""
    key = checks.row.key
    directory = files.root / files.directory(key)
    logs = tuple(None if row.conclusion == "undefined" else files.check_path(key, row.block, row.name) for row in checks.results)
    latest = SetupStore(reads.store.connect, reads.store.begin).latest(key)
    setup = None if latest is None else SetupShown(latest, directory / f"setup-{latest.run}.log")
    land = None if view.land is None else with_logs(view.land, partial(files.check_path, view.land.row.key))
    shown = replace(view, last_entry=files.last_entry(key), checks=replace(checks, logs=logs), land=land)
    return Shown(shown, directory, directory / "entry.log", setup)


def _first(rows: tuple[AttemptRow, ...]) -> AttemptRow:
    """The current attempt's attempt 1 in its step, following each repeat to the attempt it repeats."""
    by_id, found = {row.key.attempt_id: row for row in rows}, rows[0]
    while found.number > 1 and (earlier := by_id.get(found.previous_attempt_id or "")) is not None:
        found = earlier
    return found


def _ended(newer: AttemptRow, older: AttemptRow) -> str:
    """Why `older` is not current: `abandoned`, `advanced` (`newer` is attempt 1 of the step after it), or the reason
    `newer` repeated it."""
    if older.release is not None and older.release.abandoned:
        return "abandoned"
    return "advanced" if newer.previous_attempt_id is None else newer.repeat_reason or ""


def list_attempts(reads: StatusPorts, *, stuck: bool = False) -> Listed | Failed:
    """Every task's current attempt (one row per task: its highest `seq`; its latest checks attempt once its implement
    attempt is done), or (`stuck`) only those whose next action is `stuck:*`, `hold` or `unknown`."""
    try:
        every = reads.store.attempts()
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    rows = [row for before, row in zip((None, *every), every, strict=False) if before is None or before.task_id != row.task_id
            or before.backlog != row.backlog]
    found = _holding(reads, tuple(_show(reads, row, probe=not stuck or row.label is not None) for row in rows))
    return Listed(tuple(each for each in found if not stuck or each.next in ("unknown", "hold") or each.next.startswith("stuck:")))


def current_view(reads: StatusPorts, backlog: str, task_id: str) -> AttemptView | None:
    """The task's current view read now, before any hold word (`with_hold`): what a hold's cause is fenced on again
    (`hold._caused`); None when the task has no attempt. StoreUnavailable propagates."""
    rows = reads.store.attempts(backlog, task_id)
    return _show(reads, rows[0]) if rows else None


def agent_attempt(view: AttemptView) -> str:
    """The agent attempt a view's hold belongs to: its own, or (a checks view) the implement attempt it follows."""
    return view.attempt_id if view.checks is None else view.checks.row.after


def _holding(reads: StatusPorts, views: tuple[AttemptView, ...]) -> tuple[AttemptView, ...]:
    """Every view with its hold, read once for all (tl-8bh9.14.9 section 10); an unreadable hold table is `unknown`."""
    try:
        holds = HoldStore(reads.store.connect, reads.store.begin).of_attempts(tuple(map(agent_attempt, views)))
    except StoreUnavailable:
        return tuple(replace(each, next="unknown") for each in views)
    return tuple(with_hold(each, holds.get(agent_attempt(each))) for each in views)


def with_hold(view: AttemptView, row: HoldRow | None) -> AttemptView:
    """The hold decides the word after every other rule, except `unknown`: `hold` (due, or recorded and not finished)
    or `on_hold` (finished); a view with no hold and no cause keeps its own word."""
    if view.next == "unknown":
        return replace(view, hold=row)
    if row is not None:
        return replace(view, hold=row, next=hold_next(row, view.release))
    due = cause(view)
    return view if due is None else replace(view, next="hold", hold_due=due)
