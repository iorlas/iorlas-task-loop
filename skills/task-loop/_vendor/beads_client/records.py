"""bd's JSON as frozen records. Reads tolerate omitted fields and extra keys; a row without an id is malformed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from beads_client.errors import malformed


@dataclass(frozen=True)
class Dep:
    id: str
    type: str = ""
    title: str = ""
    status: str = ""
    close_reason: str = ""


@dataclass(frozen=True)
class Comment:
    author: str
    text: str
    created_at: str = ""


@dataclass(frozen=True)
class Bead:
    id: str
    title: str = ""
    status: str = ""
    issue_type: str = ""
    priority: int | None = None
    assignee: str = ""
    labels: tuple[str, ...] = ()
    parent: str = ""
    description: str = ""
    design: str = ""
    acceptance_criteria: str = ""
    notes: str = ""
    dependencies: tuple[Dep, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    lease_expires_at: str = ""
    close_reason: str = ""
    created_at: str = ""
    closed_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class NewBead:
    title: str
    issue_type: str = "task"
    priority: int | None = None
    description: str = ""
    acceptance_criteria: str = ""
    labels: tuple[str, ...] = ()
    parent: str = ""
    deps: tuple[str, ...] = ()
    no_inherit_labels: bool = False


def _str(d: dict[str, Any], key: str) -> str:
    v = d.get(key)
    return v if isinstance(v, str) else ""


def dep_of(d: dict[str, Any]) -> Dep:
    # `list` prints depends_on_id/type, `show` prints id/dependency_type
    return Dep(
        id=_str(d, "id") or _str(d, "depends_on_id"),
        type=_str(d, "dependency_type") or _str(d, "type"),
        title=_str(d, "title"),
        status=_str(d, "status"),
        close_reason=_str(d, "close_reason"),
    )


def bead_of(d: dict[str, Any]) -> Bead:
    prio, labels, deps, meta = d.get("priority"), d.get("labels"), d.get("dependencies"), d.get("metadata")
    return Bead(
        id=str(d["id"]),
        title=_str(d, "title"),
        status=_str(d, "status"),
        issue_type=_str(d, "issue_type"),
        priority=prio if isinstance(prio, int) else None,
        assignee=_str(d, "assignee"),
        labels=tuple(sorted(x for x in labels if isinstance(x, str))) if isinstance(labels, list) else (),
        parent=_str(d, "parent"),
        description=_str(d, "description"),
        design=_str(d, "design"),
        acceptance_criteria=_str(d, "acceptance_criteria"),
        notes=_str(d, "notes"),
        dependencies=tuple(dep_of(x) for x in deps if isinstance(x, dict)) if isinstance(deps, list) else (),
        metadata=dict(meta) if isinstance(meta, dict) else {},
        lease_expires_at=_str(d, "lease_expires_at"),
        close_reason=_str(d, "close_reason"),
        created_at=_str(d, "created_at"),
        closed_at=_str(d, "closed_at"),
        updated_at=_str(d, "updated_at"),
    )


def beads_of(data: object, raw: str = "") -> list[Bead]:
    """A complete bead read: one malformed row faults the whole response."""
    rows = data if isinstance(data, list) else [data] if isinstance(data, dict) and "id" in data else None
    if rows is None or any(not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"] for r in rows):
        raise malformed(raw.strip()[:500])
    return [bead_of(r) for r in rows]


def comments_of(data: object, raw: str = "") -> list[Comment]:
    if not isinstance(data, list) or any(not isinstance(r, dict) for r in data):
        raise malformed(raw.strip()[:500])
    return [Comment(author=_str(r, "author"), text=_str(r, "text"), created_at=_str(r, "created_at")) for r in data]
