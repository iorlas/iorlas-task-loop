"""The dashboard's board: one card per task, from the same reads as `tl step list` (`attempt_status.list_attempts`) plus the
tracker's titles and its ready tasks that no attempt has taken yet. Display only; the start times are the evidence
files' (an attempt row stores none), so they are as good as a file's modification time."""

from dataclasses import dataclass
from datetime import UTC, datetime

from taskloop.attempt_reads import AttemptRow
from taskloop.attempt_status import AttemptView, StatusPorts, list_attempts
from taskloop.dash_model import Board, Card, Column, DashTracker, Repeat, iso
from taskloop.evidence_files import EvidenceFiles
from taskloop.operations import Failed

STEP_COLUMN: dict[str, Column] = {"plan": "plan", "implement": "implement", "check": "checks"}


def column_of(view: AttemptView) -> Column:
    """Where a task sits: held (a hold, due or recorded), landed, land (checked, to be landed), else its step."""
    if view.next in ("hold", "on_hold"):
        return "held"
    if view.next == "landed":
        return "landed"
    if view.next == "land" or view.land is not None:
        return "land"
    return STEP_COLUMN.get(view.step, "implement")


def _repeat(view: AttemptView) -> Repeat | None:
    if view.step == "plan" and view.seq > 1:
        return Repeat("restart_at_plan", view.repeat_reason or "restarted at plan")
    if view.number > 1:
        return Repeat("repeat", view.repeat_reason or "repeat")
    return None


def _started(view: AttemptView, row: AttemptRow | None, files: EvidenceFiles) -> float | None:
    if view.hold is not None and column_of(view) == "held":
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
    slots: tuple[str, ...]


def card_of(view: AttemptView, row: AttemptRow | None, title: str, files: EvidenceFiles, now: float) -> Card:
    column = column_of(view)
    started = _started(view, row, files)
    quiet = now - view.last_command if isinstance(view.last_command, int) else None
    holding = row is not None and row.held and view.release is None
    cause = view.hold.reason if view.hold is not None else view.hold_due
    return Card(view.task_id, title, column, view.number, _repeat(view), iso(started), iso(quiet if quiet is not None else started),
                view.slot if holding else None, cause if column == "held" else None)


def build_board(ports: BoardPorts) -> Board | Failed:
    """Every task that has an attempt, and every ready task that has not (a `bd` read: a failure raises)."""
    listed = list_attempts(ports.reads)
    if isinstance(listed, Failed):
        return listed
    now = ports.reads.clock()
    rows = {row.key.attempt_id: row for row in ports.reads.store.attempts()}
    taken = {view.task_id for view in listed.attempts}
    ready = tuple(each for each in ports.tracker.ready() if each.task_id not in taken)
    titles = ports.tracker.titles(tuple(sorted(taken)))
    cards = [card_of(view, rows.get(view.attempt_id), titles.get(view.task_id, view.task_id), ports.files, now) for view in listed.attempts]
    cards += [Card(each.task_id, each.title, "waiting", 0, None, each.since, each.since, None, None) for each in ready]
    stamp = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Board(stamp, ports.slots, tuple(cards), ports.tracker.notice())
