"""Escalate repeated flakes to fix work while the test stays in the gate."""
from collections.abc import Mapping, Sequence
from typing import Final, final

from taskloop.contracts.wire import Rec
from taskloop.domain.land.queue_flake import WEEK_S, FlakeRow, score

THRESHOLD: Final = 3


@final
class Escalation(Rec):
    test: str
    row_t: float
    count: int


def escalate(
    rows: Sequence[FlakeRow], filed: Mapping[str, str], test: str, now: float,
) -> Escalation | None:
    """Request one fix bead above the weekly threshold; the test stays in the gate."""
    count = score(rows, test, now)
    if count <= THRESHOLD or test in filed:
        return None
    row_t = max(r.t for r in rows if r.test == test and now - WEEK_S <= r.t <= now)
    return Escalation(test=test, row_t=row_t, count=count)


def record(row: FlakeRow, bead: str) -> FlakeRow:
    """Record the fix bead's id on the score row."""
    return row.replace(bead=bead)
