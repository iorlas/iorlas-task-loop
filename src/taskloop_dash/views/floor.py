"""The Floor: the slots of a project as the page lists them, and the window the pieces are trimmed to."""

from collections.abc import Mapping, Sequence

from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import Phase, Piece, Slot
from taskloop.contracts.runlife import Liveness
from taskloop_dash.views import columns
from taskloop_dash.views.runfacts import Run
from taskloop_dash.views.world import ProjectIn

BACK, AHEAD = 8 * 3600.0, 2 * 3600.0  # the Floor shows 8 h back to 2 h ahead


def in_window(p: Piece, now: float) -> bool:
    return any(s.t1 >= now - BACK and s.t0 <= now + AHEAD for s in p.segs)


def hold_until(b: Bead) -> float:
    try:
        return float(b.metadata.get("hold_until") or 0)
    except (TypeError, ValueError):
        return 0.0


def slot_name(b: Bead) -> str:
    return b.title.split()[-1]


def on_slot(name: str, bead_ids: set[str], runs: Mapping[str, Sequence[Run]]) -> list[tuple[str, Run]]:
    """(bead, run) of this project's runs that ran in the slot, oldest first."""
    found = [(bead, r) for bead in bead_ids for r in runs.get(bead, ()) if r.slot == name]
    return sorted(found, key=lambda x: x[1].t0)


def slot_of(p: ProjectIn, b: Bead, runs: Mapping[str, Sequence[Run]], now: float) -> Slot:
    """One slot bead: held by a person, running a bead now, claimed with no live run, or free. `lane` is that of the slot's current or
    last call. A slot's `next` stays unset (no source until the queue names the slot)."""
    name = slot_name(b)
    seen = on_slot(name, {x.id for x in p.beads}, runs)
    lane = next((r.lane for _, r in reversed(seen) if r.lane), "")
    live = [(bead, r) for bead, r in seen if r.life is Liveness.LIVE]
    if hold_until(b) > now:
        why = columns.first_line(str(b.metadata.get("held_why") or "")) or "held"
        who = b.metadata.get("held_by") or "?"
        return Slot(id=name, name=name, lane=lane, state="held", project=p.id, idle_why=f"held by {who}: {why}")
    if live:
        bead, r = live[-1]
        cur = r.current()
        state = "look" if cur and cur.phase == Phase.LOOK else "running"
        return Slot(id=name, name=name, lane=r.lane or lane, state=state, project=p.id, bead=bead, t=r.t0)
    if b.status != "open":
        return Slot(id=name, name=name, lane=lane, state="idle", project=p.id, idle_why=f"claimed by {b.assignee or '?'}, no live run")
    return Slot(id=name, name=name, lane=lane, state="free", project=p.id)
