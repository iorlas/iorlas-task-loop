"""The claims nothing runs under, read from the same facts and the same rule as a reconcile sweep (contracts/reconcile.py `strays`). The
dashboard only reads: it shows a stray, `tl prune` and the loop's sweep are what give it back."""
from collections.abc import Mapping, Sequence

from taskloop.contracts.bead import Bead
from taskloop.contracts.fence import BEAD_GEN, SLOT_GEN, gen_of
from taskloop.contracts.reconcile import Lease, SlotFact, Stray, epoch, strays
from taskloop.contracts.runlife import Liveness
from taskloop_dash.views.runfacts import Run


def hold_until(b: Bead) -> float:
    try:
        return float(b.metadata.get("hold_until") or 0)
    except (TypeError, ValueError):
        return 0.0


def strays_of(beads: Sequence[Bead], slots: Sequence[Bead], runs: Mapping[str, Sequence[Run]], now: float) -> list[Stray]:
    """The strays of one project: its beads held in progress and its slot beads, judged against the runs that are live now."""
    live_beads = {bead for bead, rs in runs.items() if any(r.life is Liveness.LIVE for r in rs)}
    live_slots = {r.slot for rs in runs.values() for r in rs if r.life is Liveness.LIVE and r.slot}
    leases = tuple(Lease(b.id, b.assignee, gen_of(b, BEAD_GEN), epoch(b.lease_expires_at), b.id in live_beads)
                   for b in beads if b.status == "in_progress" and b.assignee and "slot" not in b.labels)
    facts = tuple(SlotFact(b.id, b.title.split()[-1], b.status == "in_progress", b.assignee, gen_of(b, SLOT_GEN), epoch(b.lease_expires_at),
                           hold_until(b), b.title.split()[-1] in live_slots) for b in slots)
    return strays(leases, facts, now)
