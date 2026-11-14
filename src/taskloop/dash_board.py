"""The dashboard's board: one card per task, from the same reads as `tl step list` (`attempt_status.list_attempts`) plus the
tracker's titles and its ready tasks that no attempt has taken yet. Display only; the start times are the evidence
files' (an attempt row stores none), so they are as good as a file's modification time."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from taskloop.agents.stop_text import stop_text
from taskloop.attempt_reads import AttemptRow, SlotUse, StoreUnavailable
from taskloop.attempt_status import AttemptView, StatusPorts, list_attempts
from taskloop.dash_model import Board, Card, Column, DashTracker, LandState, Repeat, iso
from taskloop.evidence_files import EvidenceFiles
from taskloop.land_status import LandView
from taskloop.operations import Failed
from taskloop.profile import LandMode
from taskloop.task_status import FRESH, Admission, Status, TaskStatus, blocker, landing, task_status, words

STEP_COLUMN: dict[str, Column] = {"plan": "plan", "implement": "implement", "check": "checks"}


def column_of(view: AttemptView, found: TaskStatus | None = None) -> Column:
    """Where a task sits, from its status (`task_status`): held, landed, land (checked, to be landed), waiting (abandoned or queued
    to start: no current work), else its step."""
    found = task_status(view) if found is None else found
    if found.status is Status.HELD:
        return "held"
    if found.status is Status.LANDED:
        return "landed"
    if found.status in FRESH:
        return "waiting"
    if found.status in (Status.WAITING_FOR_LAND, Status.LANDING) or view.land is not None:
        return "land"
    return STEP_COLUMN.get(view.step, "implement")


def land_state(land: LandView | None, mode: LandMode | None = None) -> LandState:
    """`landing` only while a land is observed running; any other task in the land column waits: for a person only when the
    profile says `manual`, else for the next round (also when the profile cannot be read: no policy is claimed)."""
    if landing(land):
        return "landing"
    return "manual" if mode is LandMode.MANUAL else "waiting"


def admission_of(reads: StatusPorts, approved: frozenset[str], use: SlotUse | None = None) -> Admission:
    """What the board knows of admission: the tasks the tracker lists ready, and whether a slot is free (the round's bound and label
    are its own: the board assumes none)."""
    try:
        free = reads.store.slot_use().free if use is None else use.free
    except StoreUnavailable:
        return Admission(approved, "")
    return Admission(approved, "", blocker(free, 0, 0, 1))


def _repeat(view: AttemptView) -> Repeat | None:
    if view.previous_attempt_id is not None or view.number > 1:
        return Repeat("repeat", view.repeat_reason or "repeat")
    if view.step == "plan" and view.seq > 1:
        return Repeat("restart_at_plan", view.repeat_reason or "Reason not recorded")
    return None


def _started(view: AttemptView, row: AttemptRow | None, files: EvidenceFiles, column: Column) -> float | None:
    if column == "waiting":
        return None  # no current attempt: the old one's times belong to its (past) chain
    if view.hold is not None and column == "held":
        return view.hold.held_at
    if view.land is not None and view.land.row.closed_at is not None:
        return view.land.row.closed_at
    if view.checks is not None:
        starts = [each.started_at for each in view.checks.results]
        return min(starts) if starts else view.checks.row.concluded_at
    return None if row is None else files.started_at(row.key)


@dataclass(frozen=True)
class BoardPorts:
    reads: StatusPorts
    files: EvidenceFiles
    tracker: DashTracker
    mode: Callable[[], LandMode | None] = lambda: None  # the profile's `land`, read only for a task in the land column


def tries(rows: tuple[AttemptRow, ...]) -> dict[str, int]:
    """Each attempt's try within its step, counted over the whole task: a restart at plan starts a new repeat chain whose stored
    number is 1 again, so the stored number is not unique per (step, try); this one is, and it is what the page addresses."""
    seen: dict[tuple[str, str, str], int] = {}
    found: dict[str, int] = {}
    for row in sorted(rows, key=lambda each: (each.backlog, each.task_id, each.seq)):
        seen[(row.backlog, row.task_id, row.step)] = found[row.key.attempt_id] = seen.get((row.backlog, row.task_id, row.step), 0) + 1
    return found


def card_of(
    view: AttemptView, row: AttemptRow | None, title: str, files: EvidenceFiles, now: float, number: int | None = None,
    admission: Admission | None = None, mode: Callable[[], LandMode | None] = lambda: None,
) -> Card:
    found = task_status(view, admission)
    column = column_of(view, found)
    started = _started(view, row, files, column)
    quiet = now - view.last_command if isinstance(view.last_command, int) and column != "waiting" else None
    holding = row is not None and row.held and view.release is None
    cause = view.hold.reason if view.hold is not None else view.hold_due
    rc = None if view.result.execution is None else view.result.execution.facts.rc
    cause = stop_text(view.stop, rc) or cause
    shown = view.number if number is None else number
    return Card(view.task_id, title, column, shown, _repeat(view), iso(started), iso(quiet if quiet is not None else started),
                view.slot if holding else None, cause if column == "held" else None,
                land_state(view.land, mode()) if column == "land" else None, found.status.value, words(found))


def build_board(ports: BoardPorts) -> Board | Failed:
    """Every task that has an attempt, and every ready task that has not (a `bd` read: a failure raises)."""
    listed = list_attempts(ports.reads)
    if isinstance(listed, Failed):
        return listed
    now = ports.reads.clock()
    rows = {row.key.attempt_id: row for row in listed.rows}
    numbers = {row.key.attempt_id: row.try_number for row in listed.rows}
    try:
        slots = ports.reads.store.slot_names()
        use = ports.reads.store.slot_use()
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    taken = {view.task_id for view in listed.attempts}
    listed_ready = ports.tracker.ready()
    admission = admission_of(ports.reads, frozenset(each.task_id for each in listed_ready), use)
    ready = tuple(each for each in listed_ready if each.task_id not in taken)
    titles = ports.tracker.titles(tuple(sorted(taken)))
    cards = [card_of(view, rows.get(view.attempt_id), titles.get(view.task_id, view.task_id), ports.files, now,
             numbers.get(view.attempt_id), admission, ports.mode)
             for view in listed.attempts]
    queued = TaskStatus(Status.QUEUED, wait=admission.wait)
    note = words(queued)
    cards += [Card(each.task_id, each.title, "waiting", 0, None, each.since, each.since, None, None, None, queued.status.value, note)
              for each in ready]
    stamp = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Board(stamp, slots, tuple(cards), ports.tracker.notice())
