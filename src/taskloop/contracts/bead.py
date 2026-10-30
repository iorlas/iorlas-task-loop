"""Beads as the code reads them from bd (an external contract: no `v`, never written by us). `adapters/bd.py` is the one reader."""
from typing import Any, final

import msgspec

from taskloop.contracts.ids import BeadId
from taskloop.contracts.wire import Rec


@final
class Comment(Rec):
    author: str
    text: str
    created_at: str = ""


@final
class Dep(Rec):
    """What a bead waits on. `type`: blocks, parent-child, related, ... (bd prints it `dependency_type` in show, `type` in list)."""

    id: str
    type: str = ""
    title: str = ""
    status: str = ""
    close_reason: str = ""


@final
class Bead(Rec):
    id: BeadId
    title: str
    status: str
    issue_type: str = ""
    priority: int | None = None
    assignee: str = ""
    labels: list[str] = msgspec.field(default_factory=list)
    parent: str = ""
    description: str = ""
    design: str = ""
    acceptance_criteria: str = ""
    notes: str = ""
    dependencies: list[Dep] = msgspec.field(default_factory=list)
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)  # free-form: held_by, held_bead, branch, slot, looks, ...
    lease_expires_at: str = ""
    close_reason: str = ""
    created_at: str = ""
    closed_at: str = ""
    updated_at: str = ""


@final
class BdError(Rec):
    kind: str  # lint, not_found, not_claimable, other
    missing_sections: list[str] = msgspec.field(default_factory=list)
    text: str = ""
