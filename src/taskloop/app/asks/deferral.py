"""Intake budget for agent-filed beads (tl-7i9k.19): a follow-up the engine files waits as `deferred` with the label `from-review`, and
at most `engine.intake_per_day` of them are promoted to `open` a day (oldest priority first). Off when the budget is 0."""
import time
from collections.abc import Callable
from typing import Final

from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, Beads

FROM_REVIEW: Final = "from-review"
PROMOTED: Final = "promoted:"  # + the day (YYYY-MM-DD): the label that counts a day's promotions, closed beads included


CHECK_EVERY: Final = 600  # seconds between the loop's looks at the deferred ones


def day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def defer(store: Beads, bead: BeadId) -> None:
    """The bead waits: out of `ready` until it is promoted."""
    store.update(bead, BeadPatch(status="deferred"))


def promote(store: Beads, per_day: int, today: str) -> list[BeadId]:
    """Open as many of the deferred `from-review` beads as the day has left of its budget; -> the ones opened, in order."""
    if per_day <= 0:
        return []
    left = per_day - len(store.find(BeadQuery(label=PROMOTED + today, include_closed=True)))
    if left <= 0:
        return []
    deferred = store.find(BeadQuery(status="deferred", label=FROM_REVIEW))
    waiting = sorted(deferred, key=lambda b: (b.priority if b.priority is not None else 4, str(b.id)))
    opened: list[BeadId] = []
    for bead in waiting[:left]:
        store.add_label(bead.id, PROMOTED + today)
        store.update(bead.id, BeadPatch(status="open"))
        opened.append(bead.id)
    return opened


def promote_if_due(store: Beads, per_day: int, now: float, last: float, say: Callable[[str], object]) -> float:
    """The loop's look at the deferred ones: -> when it last looked (`now` if it did; else `last`)."""
    if per_day <= 0 or now < last + CHECK_EVERY:
        return last
    try:
        for bead in promote(store, per_day, day(now)):
            say(f"intake: {bead} promoted from deferred ({per_day} a day)")
    except BdFailure:  # the next look tries again
        pass
    return now
