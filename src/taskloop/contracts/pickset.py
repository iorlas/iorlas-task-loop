"""The pick set: the owner's queue. A bead carries the `queue` label, `queue_at` (set when it was queued) fixes the order. While any
open bead carries the label, the loop and `tl next` take only queued beads, in that order; `tl loop --only` names the same set for one
run. The loop's pick (app/loop/queue.py) and the dashboard's queue strip both read this one function, so they never disagree."""
from collections.abc import Iterable, Sequence
from typing import Final, Literal, final

from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.loop import Skip
from taskloop.contracts.wire import Rec

LABEL: Final = "queue"
AT: Final = "queue_at"  # epoch milliseconds, as a string: bd metadata values are text


def at_of(b: Bead) -> float:
    try:
        return float(b.metadata.get(AT) or 0)
    except (TypeError, ValueError):
        return 0.0


def members(beads: Iterable[Bead], only: Sequence[str] = ()) -> list[BeadId]:
    """The ids the pick is limited to, in pick order; [] means no limit. `only` (tl loop --only) wins over the labels."""
    if only:
        return [BeadId(x) for x in dict.fromkeys(only)]
    held = sorted((b for b in beads if LABEL in b.labels and b.status != "closed"), key=lambda b: (at_of(b), b.id))
    return [b.id for b in held]


def outside(bead_id: str, ids: Sequence[str], only: bool = False) -> Skip | None:
    """The skip of a bead that is not in the pick set (None: it is in it, or there is no set)."""
    if not ids or bead_id in ids:
        return None
    src = "--only" if only else "the queue"
    return Skip(why=f"not in {src} ({len(ids)} chosen, first {ids[0]})", kind="queue")


def unready(b: Bead | None, bead_id: str) -> Skip:
    """Why a chosen bead is not on the ranked list: bd does not list it as ready."""
    if b is None:
        return Skip(why=f"queued {bead_id} does not exist", kind="queue")
    if b.status == "closed":
        why = "closed"
    elif b.assignee:
        why = f"taken by {b.assignee}"
    else:
        why = f"{b.status}, or a dependency is open"
    return Skip(why=f"queued but not ready: {why}", kind="queue")


@final
class QueueItem(Rec):
    """One bead of the owner's queue strip (contracts/pickset.py), in pick order. `state`: next (the loop takes it first), then, running
    (a session holds it) or skipped (`why` is the loop's own skip text, the one `tl next` prints)."""

    project: str
    bead: str
    title: str
    pos: int
    state: Literal["next", "then", "running", "skipped"]
    why: str = ""
