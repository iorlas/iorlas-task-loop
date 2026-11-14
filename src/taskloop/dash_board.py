"""The dashboard's board: one card per task, from the same reads as `tl step list` (`attempt_status.list_attempts`) plus the
tracker's titles and its ready tasks that no attempt has taken yet. Display only; the start times are the evidence
files' (an attempt row stores none), so they are as good as a file's modification time."""

from dataclasses import dataclass
from datetime import UTC, datetime

from taskloop.agents.stop_text import stop_text
from taskloop.answer_read import read as read_answer
from taskloop.attempt_reads import AttemptRow, SlotUse, StoreUnavailable
from taskloop.attempt_status import NEEDS_OWNER, AttemptView, StatusPorts, list_attempts
from taskloop.dash_model import Board, Card, Column, DashTracker, Repeat, iso
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.hold_cause import cause as hold_cause
from taskloop.operations import Failed
from taskloop.task_status import FRESH, Admission, Status, TaskStatus, blocker, task_status, words

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


def tries(rows: tuple[AttemptRow, ...]) -> dict[str, int]:
    """Each attempt's try within its step, counted over the whole task: a restart at plan starts a new repeat chain whose stored
    number is 1 again, so the stored number is not unique per (step, try); this one is, and it is what the page addresses."""
    seen: dict[tuple[str, str, str], int] = {}
    found: dict[str, int] = {}
    for row in sorted(rows, key=lambda each: (each.backlog, each.task_id, each.seq)):
        seen[(row.backlog, row.task_id, row.step)] = found[row.key.attempt_id] = seen.get((row.backlog, row.task_id, row.step), 0) + 1
    return found


def _ask(view: AttemptView, column: Column, files: EvidenceFiles) -> tuple[bool, str | None]:
    cause = view.hold.reason if view.hold is not None else view.hold_due
    current = view.hold is None or view.hold.cause_id == view.attempt_id
    if (column != "held" or not current or view.stop is not None or cause != f"failed:{NEEDS_OWNER}"
            or view.result.status != "collected" or view.result.reason != NEEDS_OWNER):
        return False, None
    try:
        answer = read_answer(files, view.result.execution, view.step, view.task_id)
    except EvidenceError:
        answer = None
    return True, None if answer is None else answer.explanation


def card_of(
    view: AttemptView, row: AttemptRow | None, title: str, files: EvidenceFiles, now: float, number: int | None = None,
    admission: Admission | None = None,
) -> Card:
    found = task_status(view, admission)
    column = column_of(view, found)
    started = _started(view, row, files, column)
    activity = None
    if found.status is Status.RUNNING and column in ("plan", "implement"):
        activity = now - view.last_command if isinstance(view.last_command, int) else started
    holding = row is not None and row.held and view.release is None
    slot = view.slot if holding else None
    if view.land is not None:
        slot = view.land.row.slot if view.land.row.holds_slot else None
    elif view.checks is not None:
        slot = view.checks.row.slot if view.checks.row.released_at is None else None
    cause = view.hold.reason if view.hold is not None else view.hold_due
    rc = None if view.result.execution is None else view.result.execution.facts.rc
    stopped = stop_text(view.stop, rc)
    shown = view.number if number is None else number
    ask, question = _ask(view, column, files)
    explanation = None
    if column == "held" and not ask:
        known = hold_cause(cause or "unknown", None if row is None else row.deadline, view.stop, rc)
        explanation = stopped or (known.what if known is not None else
                                  f"The factory held this task with recorded cause: {cause or 'unknown'}.")
    cause = stopped or cause
    return Card(view.task_id, title, column, shown, _repeat(view), iso(started), iso(activity),
                slot, cause if column == "held" else None,
                found.land if column == "land" else None, found.status.value, words(found), ask, question, explanation,
                iso(_waiting_since(view, found.status)))


def _waiting_since(view: AttemptView, status: Status) -> float | None:
    """Date only the current wait, from its owning transition rather than a previous step's start."""
    if status is Status.WAITING_FOR_LAND and view.checks is not None:
        return view.checks.row.released_at
    if status is Status.HELD and view.hold is not None:
        return view.hold.held_at
    if status is Status.ABANDONED and view.release is not None:
        return view.release.released_at
    return None


def queued_card(task_id: str, title: str, admission: Admission) -> Card:
    found = TaskStatus(Status.QUEUED, wait=admission.wait)
    return Card(task_id, title, "waiting", 0, None, None, None, None, None,
                status=found.status.value, status_note=words(found))


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
             numbers.get(view.attempt_id), admission)
             for view in listed.attempts]
    cards += [queued_card(each.task_id, each.title, admission) for each in ready]
    stamp = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Board(stamp, slots, tuple(cards), ports.tracker.notice())
