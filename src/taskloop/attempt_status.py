"""Every step command's status read (`tl step show`, `tl step list` and the round's snapshot): a task's current attempt
with its entry observation, collected result, deadline and the `Next` word a person acts on. Read-only: values in,
values out; `result_data.as_data` is the one JSON shape."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import Literal

from taskloop.attempt import collect, succeeded
from taskloop.attempt_reads import AttemptRow, PublishedRow, ReleaseRow
from taskloop.attempt_store import AttemptStore, StoreUnavailable
from taskloop.attempt_types import ATTEMPTS, REPEATABLE, AttemptKey, AttemptResult, EntryIdentity, Observe, Unsettled
from taskloop.evidence_files import EvidenceFiles
from taskloop.operations import Clock, Failed

type EntryState = Literal["none", "running", "gone", "different_process", "unknown"]
type Stuck = Literal["stuck:expired_admitted", "stuck:entry_lost", "stuck:hung", "stuck:uncollected", "stuck:conflict"]
type Next = Literal["start", "wait", "verify", "repeat", "repeats_exhausted", "release", "publish", "done", "unknown"] | Stuck
type Leftovers = Callable[[AttemptKey], Unsettled | None]  # read-only Git and file reads of a step still to settle


@dataclass(frozen=True)
class StatusPorts:
    store: AttemptStore
    observe: Observe
    clock: Clock
    leftovers: Leftovers
    boot: Callable[[], str | None]  # this machine's boot id, None when unknown (then no attempt counts as rebooted)


@dataclass(frozen=True)
class AttemptView:
    backlog: str
    task_id: str
    step: str  # the step the attempt belongs to (`plan`)
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
    view: AttemptView
    directory: Path
    entry_log: Path


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


def _show(reads: StatusPorts, row: AttemptRow, *, probe: bool = True) -> AttemptView:
    """A task's current attempt. `probe`: read the leftovers of a step still to settle (Git and slot reads); never for
    a listing that keeps only stuck or unknown attempts, which a `verify`, `repeat` or `repeats_exhausted` step never is."""
    entry: EntryState = "none"
    if row.entry is not None:
        seen = reads.observe(row.entry)
        entry = "running" if seen == "matching" else seen
    result = collect(reads.store, row.key)
    expired = reads.clock() >= row.deadline
    rebooted = row.entry is not None and reads.boot() not in (None, row.entry[2])
    step = _released(row, next_action(row.phase, entry, result, expired, rebooted=rebooted), succeeded(result))
    found = (row.backlog, row.task_id, row.step, row.key.attempt_id, row.slot, row.phase)
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
    last = files.last_entry(rows[0].key)
    return Shown(replace(_show(reads, rows[0]), earlier=earlier, last_entry=last), directory, directory / "entry.log")


def _ended(newer: AttemptRow, older: AttemptRow) -> str:
    """Why `older` is not current: `abandoned`, or the reason `newer` repeated it."""
    return "abandoned" if older.release is not None and older.release.abandoned else newer.repeat_reason or ""


def list_attempts(reads: StatusPorts, *, stuck: bool = False) -> Listed | Failed:
    """Every task's current attempt (one row per task: its highest `seq`), or (`stuck`) only those whose next action is
    `stuck:*` or `unknown`."""
    try:
        every = reads.store.attempts()
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    rows = [row for before, row in zip((None, *every), every, strict=False) if before is None or before.task_id != row.task_id
            or before.backlog != row.backlog]
    found = (_show(reads, row, probe=not stuck) for row in rows)
    return Listed(tuple(each for each in found if not stuck or each.next == "unknown" or each.next.startswith("stuck:")))
