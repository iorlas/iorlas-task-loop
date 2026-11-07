"""The beads port: bd as the engine sees it (requests, the failure type, the Protocol); implemented by adapters.bd and the memory beads."""
from typing import Any, NamedTuple, Protocol, final

import msgspec

from tlkernel.bead import BdError, Bead, Comment
from tlkernel.ids import BeadId
from tlkernel.wire import Rec


@final
class NewBead(Rec):
    title: str
    issue_type: str = "task"
    priority: int | None = None
    description: str = ""
    acceptance_criteria: str = ""
    labels: list[str] = msgspec.field(default_factory=list)
    parent: str = ""
    deps: list[str] = msgspec.field(default_factory=list)
    no_inherit_labels: bool = False


@final
class BeadPatch(Rec):
    """What `update` changes; a field left at its default is not touched. assignee "" clears it."""

    status: str = ""
    if_assignee: str = ""  # apply only while this actor still holds the bead (bd checks it atomically)
    assignee: str | None = None
    description: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None  # the whole metadata object replaced (set_metadata changes single keys)
    set_metadata: dict[str, str] = msgspec.field(default_factory=dict)
    unset_metadata: list[str] = msgspec.field(default_factory=list)


@final
class BeadQuery(Rec):
    status: str = ""
    label: str = ""
    include_closed: bool = False


class BdFailure(Exception):
    """bd refused or failed. `error.kind`: lint (missing sections), not_found, not_claimable, other."""

    def __init__(self, error: BdError) -> None:
        super().__init__(f"{error.kind}: {error.text}")
        self.error = error


class DoltPush(NamedTuple):
    """The outcome of a Dolt sync: code 0 synced; 1 error or a rejected push; 2 merge conflict; 3 retries exhausted; 4 stuck."""
    code: int
    text: str


class Beads(Protocol):
    """bd as the code uses it. Reads of an unknown bead answer None or []; `show` of a bead when bd itself fails (down, locked)
    raises BdFailure, so "no such bead" is never confused with "could not ask". A refused write raises BdFailure,
    except `claim`/`unclaim`, which answer whether the bead changed hands."""

    def show(self, bead: BeadId) -> Bead | None: ...
    def comments(self, bead: BeadId) -> list[Comment]: ...
    def find(self, query: BeadQuery) -> list[Bead]: ...
    def ready(self, label: str = "") -> list[Bead]: ...
    def create(self, new: NewBead) -> BeadId:
        """-> the new bead's id."""
        ...
    def update(self, bead: BeadId, patch: BeadPatch) -> None: ...
    def claim(self, bead: BeadId) -> bool: ...
    def unclaim(self, bead: BeadId, force: bool = False) -> bool: ...
    def heartbeat(self, bead: BeadId) -> None: ...
    def close(self, bead: BeadId, reason: str, if_assignee: str = "") -> None:
        """Close the bead. `if_assignee`: only while that actor still holds it (bd close has no such guard, so a same-value assignee
        update fences first, then bd close records the reason); a mismatch raises BdFailure and changes nothing."""
        ...
    def add_comment(self, bead: BeadId, text: str) -> None: ...
    def add_label(self, bead: BeadId, label: str, if_assignee: str = "") -> None:
        """Add a label. `if_assignee`: only while that actor still holds the bead (a same-value update fences first, as for `close`)."""
        ...
    def remove_label(self, bead: BeadId, label: str) -> None: ...
    def provenance(self, bead: BeadId, kind: str, source: str, ref: str = "", ref_kind: str = "", at: str = "",
                   payload: str = "") -> None: ...
    def dolt_push(self) -> DoltPush:
        """Sync bd's Dolt data with its remote (pull, then push). -> DoltPush; never raises for bd's refusal."""
        ...
    def at(self, cwd: str) -> Beads:
        """The same store asked about the tracker in `cwd`."""
        ...
