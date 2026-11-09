"""Map the owning tracker client's typed read into the task inspection operation."""

from beads_client import BdError, TaskReadClient

from taskloop.task import TaskBinding, TaskDependency, TaskInspection, TaskInspectionError, TaskReference


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
