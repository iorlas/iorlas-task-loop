"""The dashboard's cost page (GET /api/cost): sums of time, tokens and cost over the engine logs, in the wire form of
taskloop.contracts.dash (its own module: dash.py is at its size cap)."""
from typing import Annotated, ClassVar, final

import msgspec

from taskloop.contracts.wire import Rec


@final
class CostRow(Rec):
    """One bucket's sums over the runs in the window. `cost` adds only the calls whose cost is known; `unknown` counts the calls whose
    cost is not (their tokens and time are still summed), so a missing cost is never shown as 0. `bead` is set on a drill-down row."""

    key: str
    secs: int = 0
    tokens: Annotated[int, msgspec.Meta(description="fresh tokens: input - cached + output")] = 0
    cost: float = 0.0
    calls: int = 0
    unknown: int = 0
    bead: str = ""


@final
class CostPage(Rec):
    """The sums of the engine logs still kept, per stage, role, lane and bead, and per stage of each bead (`drill`). Stage time is the
    steps' time; role and lane time is the calls' (a lane adds its checks' run time). `waits` is the engine's own waits by what it
    waited for (a lane, a resource, a lock ...). A run is in the window when its newest record is; `last` > 0 takes that many newest
    runs instead."""

    V: ClassVar[int] = 1
    t: float
    window: str
    runs: int = 0
    stages: list[CostRow] = msgspec.field(default_factory=list)
    roles: list[CostRow] = msgspec.field(default_factory=list)
    lanes: list[CostRow] = msgspec.field(default_factory=list)
    beads: list[CostRow] = msgspec.field(default_factory=list)
    drill: list[CostRow] = msgspec.field(default_factory=list)
    waits: list[CostRow] = msgspec.field(default_factory=list)
