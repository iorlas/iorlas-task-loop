"""Beads as the code reads them from bd (an external contract: no `v`, never written by us)."""
from dataclasses import field
from typing import Any

from taskloop.contracts.codec import record


@record
class Comment:
    author: str
    text: str
    created_at: str = ""


@record
class SlotHold:
    """A slot kept off the loop (a person, screenshots): bead metadata."""

    until: float | None = None
    why: str = ""


@record
class LookEntry:
    """One verdict of the look judge, as kept in bead metadata."""

    item: str
    verdict: str
    where: str = ""
    why: str = ""


@record
class BeadMeta:
    held_bead: str = ""
    slot_hold: SlotHold | None = None
    looks: list[LookEntry] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


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
    dependencies: list[str] = field(default_factory=list)
    metadata: BeadMeta = field(default_factory=BeadMeta)
    lease_expires_at: str = ""


@record
class BdError:
    kind: str
    missing_sections: list[str] = field(default_factory=list)
    text: str = ""
