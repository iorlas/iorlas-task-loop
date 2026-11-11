"""Typed task inspection data scoped to an explicitly configured backlog."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class TaskScope:
    """A configured logical backlog, not a discovered global tracker identity."""

    backlog: str
    adapter: Literal["beads"] = "beads"

    def __post_init__(self) -> None:
        if not self.backlog.strip():
            raise TaskInspectionError("invalid_binding", "An explicit nonempty backlog is required")


@dataclass(frozen=True)
class TaskReference:
    scope: TaskScope
    task_id: str


@dataclass(frozen=True)
class TaskBinding:
    scope: TaskScope
    tracker_root: Path

    def __post_init__(self) -> None:
        if not self.tracker_root.is_absolute():
            raise TaskInspectionError("invalid_binding", "The tracker binding requires an absolute tracker root")


@dataclass(frozen=True)
class TaskDependency:
    reference: TaskReference
    relationship: str
    title: str
    status: str


@dataclass(frozen=True)
class TaskInspection:
    """`status` and `assignee` are the tracker's words as read (empty when it has none): what an advance confirms."""

    reference: TaskReference
    title: str
    requirements: str
    acceptance: str
    dependencies: tuple[TaskDependency, ...]
    status: str
    assignee: str


class TaskInspectionError(Exception):
    """A truthful inspection refusal with optional owning-backend diagnostics."""

    def __init__(
        self,
        kind: Literal["not_found", "malformed", "tracker_unavailable", "invalid_binding"],
        message: str,
        *,
        reference: TaskReference | None = None,
        backend_kind: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.reference = reference
        self.backend_kind = backend_kind
