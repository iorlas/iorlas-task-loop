"""Beads as the code reads them from bd (an external contract: no `v`, never written by us). `adapters/bd.py` is the one reader."""
from dataclasses import field
from typing import Any

from taskloop.contracts.codec import record


@record
class Comment:
    author: str
    text: str
    created_at: str = ""


@record
class Dep:
    """What a bead waits on. `type`: blocks, parent-child, related, ... (bd prints it `dependency_type` in show, `type` in list)."""

    id: str
    type: str = ""
    title: str = ""
    status: str = ""


@record
class Bead:
    id: str
    title: str
    status: str
    issue_type: str = ""
    priority: int | None = None
    assignee: str = ""
    labels: list[str] = field(default_factory=list)
    parent: str = ""
    description: str = ""
    design: str = ""
    acceptance_criteria: str = ""
    notes: str = ""
    dependencies: list[Dep] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)  # free-form: held_by, held_bead, branch, slot, looks, ...
    lease_expires_at: str = ""


@record
class BdError:
    kind: str  # lint, not_found, not_claimable, other
    missing_sections: list[str] = field(default_factory=list)
    text: str = ""
