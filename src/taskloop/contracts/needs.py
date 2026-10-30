"""The needs-you list's row (Snapshot.needs, contracts/dash.py): kept apart so dash.py stays under its cap."""
from typing import Literal, final

from taskloop.contracts.wire import Rec

NeedKind = Literal["label", "block", "parked", "capped", "paused", "slot_held", "slot_aside", "slot_setup", "stray", "stalled", "absent"]


@final
class NeedRow(Rec):
    """One thing that waits on the owner with no ask to answer: the bead (None for a loop or a slot), why, and since when (None when no
    record says). The list is a view over records the engine already writes; `Snapshot.needs` is sorted oldest first."""

    kind: NeedKind
    project: str
    bead: str | None
    why: str
    since: float | None = None
    until: float | None = None
    title: str = ""
