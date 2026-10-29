"""Beads as the code reads them from bd (an external contract: no `v`, never written by us). `adapters/bd.py` is the one reader."""
from typing import Any

import msgspec

from taskloop.contracts.wire import Rec


def is_bead_id(text: object) -> bool:
    """A letter or digit first, then letters, digits, '_', '.' and '-': never something bd would read as an option."""
    s = text if isinstance(text, str) else ""
    return bool(s) and s[0].isalnum() and s.isascii() and all(c.isalnum() or c in "_.-" for c in s)


class Comment(Rec):
    author: str
    text: str
    created_at: str = ""


class Dep(Rec):
    """What a bead waits on. `type`: blocks, parent-child, related, ... (bd prints it `dependency_type` in show, `type` in list)."""

    id: str
    type: str = ""
    title: str = ""
    status: str = ""
    close_reason: str = ""


class Bead(Rec):
    id: str
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


class BdError(Rec):
    kind: str  # lint, not_found, not_claimable, other
    missing_sections: list[str] = msgspec.field(default_factory=list)
    text: str = ""
