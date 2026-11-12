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


@dataclass(frozen=True)
class TaskFacts:
    """One task as the tracker holds it, for a read-only view. `created_at` and `updated_at` are the tracker's own ISO
    strings as the client returns them (not converted; empty when absent); `notes` and `design` are empty when absent."""

    task_id: str
    title: str
    status: str
    priority: int | None
    labels: tuple[str, ...]
    assignee: str | None
    description: str
    design: str
    acceptance: str
    notes: str
    dependencies: tuple[str, ...]  # ids
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TaskComment:
    """One tracker comment; `at` is the tracker's ISO string as returned (empty when absent)."""

    author: str
    at: str
    text: str


@dataclass(frozen=True)
class ReadyTitle:
    """One task `bd ready` lists: what a listing shows of it."""

    task_id: str
    title: str
    priority: int | None
    created_at: str


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
