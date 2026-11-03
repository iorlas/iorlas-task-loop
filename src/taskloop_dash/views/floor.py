"""The Floor: the slots of a project as the page lists them, and the window the pieces are trimmed to."""

from collections.abc import Mapping, Sequence

from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import Phase, Piece, Slot
from taskloop.contracts.events import Claim, SlotSetup, SlotTake, Stage
from taskloop.contracts.ids import BeadId
from taskloop.contracts.runlife import Liveness
from taskloop.contracts.slots import SlotTable
from taskloop.contracts.slottable import LiveSlot, build_slot_table, slot_view
from taskloop_dash.tails import parse_ts
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


def table_of(p: ProjectIn, runs: Mapping[str, Sequence[Run]], now: float) -> SlotTable:
    """The project's slot table (taskloop.contracts.slottable): configured lanes exist even before a slot bead or its first run does."""
    src = p.slot_source
    live = {}
    for b in p.beads:
        for r in runs.get(b.id, ()):
            if r.life is Liveness.LIVE and r.slot:
                live[r.slot] = LiveSlot(run=r.name, bead=b.id, since=str(r.t0))
    open_ids = [x.id for x in p.beads if x.status in ("open", "in_progress")]
    return build_slot_table(p.slots, src.count, live, src.dirs, now, src.source, src.sha, open_ids)


def slots_of(p: ProjectIn, runs: Mapping[str, Sequence[Run]], now: float) -> list[Slot]:
    """The Floor's lanes, one per row of the slot table; a free slot above the count is retiring and gets no lane."""
    beads = {slot_name(b): b for b in p.slots}
    return [slot_of(p, beads.get(v.id) or Bead(id=BeadId("slot-" + v.id), title="slot " + v.id, status="open"), runs, now)
            for v in table_of(p, runs, now).slots if v.state != "retiring"]


def on_slot(name: str, bead_ids: set[str], runs: Mapping[str, Sequence[Run]]) -> list[tuple[str, Run]]:
    """(bead, run) of this project's runs that ran in the slot, oldest first."""
    found = [(bead, r) for bead in bead_ids for r in runs.get(bead, ()) if r.slot == name]
    return sorted(found, key=lambda x: x[1].t0)


def slot_of(p: ProjectIn, b: Bead, runs: Mapping[str, Sequence[Run]], now: float) -> Slot:
    """One slot bead as a lane: held, running, starting a known bead, claimed with no known work (a stray), or free. `lane` is that of
    the slot's current or last call. The state is the table's (`slot_view`); the lane adds what only the runs and events know."""
    name = slot_name(b)
    seen = on_slot(name, {x.id for x in p.beads}, runs)
    lane = next((r.lane for _, r in reversed(seen) if r.lane), "")
    live = [(bead, r) for bead, r in seen if r.life is Liveness.LIVE]
    run = LiveSlot(run=live[-1][1].name, bead=live[-1][0], since=str(live[-1][1].t0)) if live else None
    dirs = p.slot_source.dirs
    v = slot_view(name, b, run, dirs is None or name in dirs, False, now, {x.id for x in p.beads if x.status in ("open", "in_progress")})
    if v.state == "held":
        return Slot(id=name, name=name, lane=lane, state="held", project=p.id, idle_why=v.idle_why)
    if v.state == "running":
        bead, r = live[-1]
        cur = r.current()
        return Slot(id=name, name=name, lane=r.lane or lane, state="look" if cur and cur.phase == Phase.LOOK else "running",
                    project=p.id, bead=bead, t=r.t0)
    if v.state == "setup":
        t = parse_ts(b.metadata.get("held_since")) or parse_ts(b.updated_at)
        return Slot(id=name, name=name, lane=lane, state="starting", project=p.id, bead=v.bead, t=t, idle_why=v.idle_why,
                    startup=startup_of(p, name, v.bead, t, now))
    if v.state in ("claimed", "dead"):
        stray = next((x for x in p.strays if x.kind == "slot" and x.ref == b.id), None)
        return Slot(id=name, name=name, lane=lane, state="idle", project=p.id, idle_why=stray.why if stray else v.idle_why)
    return Slot(id=name, name=name, lane=lane, state="free", project=p.id)


def startup_of(p: ProjectIn, slot: str, bead: str, since: float | None, now: float) -> str:
    """Only events of this claim: slot events may have no bead, bead events must name this bead."""
    if since is None:
        return ""
    phases: list[str] = []
    for e in sorted(p.events, key=lambda e: e.t):
        if not since <= e.t <= now or (e.bead and e.bead != bead):
            continue
        label = ""
        if isinstance(e, (Claim, SlotTake)) and e.slot == slot:
            label = "claimed"
        elif isinstance(e, SlotSetup) and e.slot == slot:
            label = "setup" if e.exit == 0 else "setup failed"
        elif isinstance(e, Stage) and e.bead == bead and e.step in ("setup", "rebase"):
            label = e.step
        if label and (not phases or phases[-1] != label):
            phases.append(label)
    return " · ".join(phases[-3:])


def stray_rows(p: ProjectIn) -> list[Slot]:
    """A bead claimed by an engine actor with no live run, as an idle row like a stray slot's (its line says why and whether the lease
    ended); `tl prune`, the loop's step and the next run of the bead give it back."""
    return [Slot(id=x.ref, name=x.ref, lane="", state="idle", project=p.id, idle_why=x.why) for x in p.strays if x.kind == "bead"]
