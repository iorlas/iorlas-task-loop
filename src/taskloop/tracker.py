"""Map the owning tracker client's typed reads into the task inspection operation and the scheduling round's ready rows."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from beads_client import BdError, Bead, ReadyReadClient, TaskReadClient

from taskloop.task import TaskBinding, TaskDependency, TaskInspection, TaskInspectionError, TaskReference

HELD: Final = "held"  # the tracker label a hold adds, read for control only to leave a hand-paused task alone
GONE: Final = "no issue found matching"  # bd 1.3.1 on a deleted bead (`resolving X: no issue found matching "X"`), classified `other`
ACTOR: Final = "taskloop"  # the factory's tracker actor: its claims, and the assignee a round still treats as its own


class ReadyRows(TaskReadClient, ReadyReadClient, Protocol):
    """The tracker's ready set, its in-progress list and single-task read: no write verb is reachable through it."""

    def find(self, status: str = "", label: str = "", *, include_closed: bool = False) -> list[Bead]: ...


def leaked_claim(task: str) -> str:
    """The one wording for a start whose compensation could not return the claim: what is true, and the person's check."""
    return (f"the tracker claim on {task} may still be held by {ACTOR}, so the task stays in progress for {ACTOR} and is not ready "
            f"again until a person returns the claim: check `bd show {task}`; `bd unclaim {task} --if-assignee {ACTOR}`")


@dataclass(frozen=True)
class TaskRow:
    """What selection needs of one task: its own priority (None: missing), its containment parent and its assignee."""

    task_id: str
    priority: int | None
    parent: str
    assignee: str
    held: bool = False  # carries the `held` label: a hold of the factory's, or a person's pause


def _failure(error: BdError, what: str) -> TaskInspectionError:
    kind = "malformed" if error.kind == "malformed" else "tracker_unavailable"
    return TaskInspectionError(kind, error.text or str(error) or what, backend_kind=error.kind)


def _row(record: Bead) -> TaskRow:
    return TaskRow(record.id, record.priority, record.parent, record.assignee, HELD in record.labels)


def inspect_task(binding: TaskBinding, client: TaskReadClient, task_id: str) -> TaskInspection:
    """Read exactly one task and preserve its configured scope and original prose."""
    reference = TaskReference(binding.scope, task_id)
    try:
        record = client.show(task_id)
    except BdError as error:
        gone = error.kind == "other" and GONE in error.text  # bd answers a deleted task with an error, not an empty read
        kind = "malformed" if error.kind == "malformed" else "not_found" if gone else "tracker_unavailable"
        raise TaskInspectionError(kind, error.text or str(error), reference=reference, backend_kind=error.kind) from error
    if record is None:
        raise TaskInspectionError("not_found", f"Task {task_id!r} was not found in backlog {binding.scope.backlog!r}", reference=reference)
    dependencies = tuple(
        TaskDependency(TaskReference(binding.scope, dependency.id), dependency.type, dependency.title, dependency.status)
        for dependency in record.dependencies
    )
    return TaskInspection(
        reference, record.title, record.description, record.acceptance_criteria, dependencies, record.status, record.assignee
    )


def _lapsed(record: Bead, now: float) -> bool:
    """The factory's own claim whose lease ran out: after a factory.db discard nothing renews it and no attempt owns it."""
    try:
        return record.assignee == ACTOR and datetime.fromisoformat(record.lease_expires_at).timestamp() <= now
    except ValueError:  # no lease recorded: not ours to take
        return False


def ready_rows(client: ReadyRows, label: str, now: float, retake: bool = False) -> tuple[TaskRow, ...]:
    """One tracker read of the ready tasks carrying `label`, in the tracker's order; with `retake` (the person's statement
    that factory.db was discarded: `--retake-lapsed`) then the factory's own in-progress ones carrying it whose lease expired
    at `now`, which `bd ready` never lists (a round skips one that has an attempt here). Without it no in-progress task is
    read: another factory.db on the tracker may own it. A failed read raises, never `()`."""
    try:
        ready = client.ready(label)
        seen = {record.id for record in ready}
        found = client.find("in_progress", label) if retake else []
        lapsed = [record for record in found if record.id not in seen and _lapsed(record, now)]
        return tuple(_row(record) for record in (*ready, *lapsed))
    except BdError as error:
        raise _failure(error, "ready read failed") from error


def ancestry(client: ReadyRows, rows: Sequence[TaskRow]) -> Callable[[str], TaskRow | None]:
    """A lookup of one task by id for ancestor chains: the ready rows first, else one `show` per unique id per round
    (memoized, failures included). None: the tracker says it does not exist; a failed read raises TaskInspectionError."""
    known: dict[str, TaskRow | TaskInspectionError | None] = {row.task_id: row for row in rows}

    def lookup(task_id: str) -> TaskRow | None:
        if task_id not in known:
            try:
                record = client.show(task_id)
                known[task_id] = None if record is None else _row(record)
            except BdError as error:
                known[task_id] = _failure(error, "show failed")
        found = known[task_id]
        if isinstance(found, TaskInspectionError):
            raise found
        return found

    return lookup
