"""The queue strip: the beads the owner queued (`queue` label, contracts/pickset.py), in pick order. While a loop runs, each bead's
state and reason are the loop's own queue rows, the ones `tl next` prints (both come from app/loop/queue.py rank_ready); with no loop
the strip says what the bead's own record shows."""

from taskloop.contracts import pickset
from taskloop.contracts.pickset import QueueItem
from taskloop_dash.views.needs import live_loops
from taskloop_dash.views.world import ProjectIn, World


def items_of(w: World, p: ProjectIn) -> list[QueueItem]:
    ids = pickset.members(p.beads)
    by_id = {b.id: b for b in p.beads}
    live = live_loops(p, w.now)
    rows = {r.bead: r for r in max(live, key=lambda s: s.t).queue} if live else {}
    out: list[QueueItem] = []
    for n, i in enumerate(ids, 1):
        b = by_id[i]
        row = rows.get(i)
        if row is not None and row.skip is not None:
            state, why = "skipped", row.skip.why
        elif row is not None:
            state, why = ("next" if row.ahead == 0 else "then"), row.reason
        elif b.assignee:
            state, why = "running", b.assignee
        elif live:
            state, why = "running", "taken or not ready"
        else:
            state, why = ("next" if n == 1 else "then"), "no loop running"
        out.append(QueueItem(project=p.id, bead=i, title=b.title[:100], pos=n, state=state, why=why))
    return out
