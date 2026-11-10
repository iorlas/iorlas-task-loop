"""Map the owning tracker client's typed reads into the task inspection operation and the scheduling round's ready rows."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from beads_client import BdError, Bead, ReadyReadClient, TaskReadClient

from taskloop.task import TaskBinding, TaskDependency, TaskInspection, TaskInspectionError, TaskReference

ACTOR: Final = "taskloop"  # the factory's tracker actor: its claims, and the assignee a round still treats as its own


class ReadyRows(TaskReadClient, ReadyReadClient, Protocol):
    """The tracker's ready set and single-task read: no write verb is reachable through it."""


@dataclass(frozen=True)
class TaskRow:
    """What selection needs of one task: its own priority (None: missing), its containment parent and its assignee."""

    task_id: str
    priority: int | None
    parent: str
    assignee: str


def _failure(error: BdError, what: str) -> TaskInspectionError:
    kind = "malformed" if error.kind == "malformed" else "tracker_unavailable"
    return TaskInspectionError(kind, error.text or str(error) or what, backend_kind=error.kind)


def _row(record: Bead) -> TaskRow:
    return TaskRow(record.id, record.priority, record.parent, record.assignee)


def inspect_task(binding: TaskBinding, client: TaskReadClient, task_id: str) -> TaskInspection:
    """Read exactly one task and preserve its configured scope and original prose."""
    reference = TaskReference(binding.scope, task_id)
    try:
        record = client.show(task_id)
    except BdError as error:
        kind = "malformed" if error.kind == "malformed" else "tracker_unavailable"
        raise TaskInspectionError(kind, error.text or str(error), reference=reference, backend_kind=error.kind) from error
    if record is None:
        raise TaskInspectionError("not_found", f"Task {task_id!r} was not found in backlog {binding.scope.backlog!r}", reference=reference)
    dependencies = tuple(
        TaskDependency(TaskReference(binding.scope, dependency.id), dependency.type, dependency.title, dependency.status)
        for dependency in record.dependencies
    )
    return TaskInspection(reference, record.title, record.description, record.acceptance_criteria, dependencies)


def ready_rows(client: ReadyRows, label: str) -> tuple[TaskRow, ...]:
    """One tracker read of the ready tasks carrying `label`, in the tracker's order; a failed read raises, never `()`."""
    try:
        return tuple(_row(record) for record in client.ready(label))
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
