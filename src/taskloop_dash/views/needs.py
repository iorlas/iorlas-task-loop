"""The needs-you list and the loop-health strip: a view over records the engine already writes, read only.

One row per thing that waits on the owner and has no ask to answer (asks are the Decisions tab): a bead the loop refused or needs
something of (labels), a blocked bead, a bead the loop will not take again (the queue's `parked` and `capped` skips; the Park record
gives the time), a run paused for the network, a lane that is out, a slot held, set aside or whose setup failed, a claim nothing runs
under, a stalled loop and an absent one. A bead appears once, under the first kind that names it.

Not shown, because no record the dashboard may read holds it: the storm stop (its file is read by an adapter, not by contracts), the
network wait of a loop that has no bead in it (in memory only), and a Park whose bead the queue does not list (no live loop)."""

from collections.abc import Sequence
from typing import Final, Literal

from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import LoopInfo
from taskloop.contracts.events import Block, EventRec, SlotAside, SlotHold, SlotSetup
from taskloop.contracts.loop import LoopState
from taskloop.contracts.needs import NeedRow
from taskloop.contracts.reconcile import LOOP_ABSENT_S, LOOP_STALL_S, LoopFact, loop_absent
from taskloop.contracts.snapshots import LaneStatus, NeedInput
from taskloop_dash.views import floor
from taskloop_dash.views.board import LOOP_STALE, ask_facts, blockers, is_work, when
from taskloop_dash.views.lanecards import state_of
from taskloop_dash.views.world import ProjectIn, World

WAITS: Final = {  # the labels that put a bead on the owner, and what each asks of him
    "needs-ac": "needs acceptance criteria",
    "needs-info": "needs information from the owner",
    "owner-taste": "waits on the owner's taste",
    "owner-look": "waits on the owner's look",
}


def live_loops(p: ProjectIn, now: float) -> list[LoopState]:
    return [s for s in p.loops if now - s.t < LOOP_STALE]


def last_event[E: EventRec](p: ProjectIn, kinds: type[E], slot: str = "", bead: str = "") -> E | None:
    """The newest event of the record class `kinds` (a class or a union of classes) of this slot (events that name one) or bead."""
    hits = [e for e in p.events if isinstance(e, kinds) and (not slot or getattr(e, "slot", "") == slot) and (not bead or e.bead == bead)]
    return max(hits, key=lambda e: e.t, default=None)


def has_ask(w: World, b: Bead) -> bool:
    return any(ask_facts(w.asks.get(b.id))[:2])


def ready_count(w: World, p: ProjectIn) -> int:
    """Beads the loop can take now: the newest live loop's own queue when one runs, else the open work beads nothing holds back."""
    live = live_loops(p, w.now)
    if live:
        return sum(1 for r in max(live, key=lambda s: s.t).queue if r.skip is None)
    by_id = {b.id: b for b in p.beads}
    return sum(1 for b in p.beads if is_work(b) and b.status == "open" and not b.assignee and not WAITS.keys() & set(b.labels)
               and not blockers(b, by_id) and not has_ask(w, b) and "blocked" not in b.labels)


def health(w: World, p: ProjectIn) -> LoopInfo:
    """The loop strip of one repo. Absent is the reconcile NoLoop rule (contracts.reconcile.loop_absent) on this repo's loop files;
    stalled: a loop beats and holds no bead, ready beads wait, and the repo logged no event since LOOP_STALL_S (a loop that started
    later counts from its start)."""
    now, live = w.now, live_loops(p, w.now)
    beat = max((s.t for s in p.loops), default=None)
    ready = ready_count(w, p)
    quiet = max([e.t for e in p.events] + [min(s.started for s in live)] if live else [], default=None)
    facts = tuple(LoopFact(s.pid, s.started, s.t) for s in live)
    state: Literal["ok", "stalled", "absent"] = "ok"
    if loop_absent(facts, ready, beat or 0.0, now, LOOP_ABSENT_S):
        state = "absent"
    elif live and ready > 0 and not any(s.bead for s in live) and quiet is not None and now - quiet > LOOP_STALL_S:
        state = "stalled"
    return LoopInfo(project=p.id, running=bool(live), last_activity=beat, ready=ready, quiet_since=quiet, health=state)


def since_of(b: Bead) -> float | None:
    return when(b.updated_at) or when(b.created_at)


def bead_rows(w: World, p: ProjectIn) -> list[NeedRow]:
    out: list[NeedRow] = []
    live = live_loops(p, w.now)
    skips = {r.bead: (r, r.skip) for r in max(live, key=lambda s: s.t).queue if r.skip is not None} if live else {}
    for b in p.beads:
        if b.status == "closed" or "slot" in b.labels or b.issue_type == "epic" or has_ask(w, b):
            continue
        hit = next((x for x in WAITS if x in b.labels), None)
        if not hit and not is_work(b):
            continue
        park = skips.get(b.id)
        if hit:
            out.append(NeedRow(kind="label", project=p.id, bead=b.id, why=WAITS[hit], since=since_of(b), title=b.title))
        elif b.status == "blocked":
            ev = last_event(p, Block, bead=b.id)
            out.append(NeedRow(kind="block", project=p.id, bead=b.id, why=ev.why if ev and ev.why else "blocked, no reason recorded",
                               since=ev.t if ev else since_of(b), title=b.title))
        elif park and park[1].kind in ("parked", "capped"):
            rec = w.parks.get(b.id)
            out.append(NeedRow(kind=park[1].kind, project=p.id, bead=b.id, why=park[1].why, until=park[1].until,
                               since=rec.t if rec else park[0].since, title=b.title))
        elif b.id in w.net_pauses:
            out.append(NeedRow(kind="paused", project=p.id, bead=b.id, why="paused for the network",
                               since=w.net_pauses[b.id].t, title=b.title))
    return out


def slot_rows(w: World, p: ProjectIn) -> list[NeedRow]:
    out: list[NeedRow] = []
    for b in p.slots:
        name = floor.slot_name(b)
        if floor.hold_until(b) > w.now:
            ev = last_event(p, SlotHold | SlotAside, slot=name)
            out.append(NeedRow(kind="slot_aside" if isinstance(ev, SlotAside) else "slot_held", project=p.id, bead=None,
                               why=f"slot {name}: {b.metadata.get('held_why') or (ev and ev.why) or 'held'}",
                               since=ev.t if ev else None, until=floor.hold_until(b)))
        setup = last_event(p, SlotSetup, slot=name)
        if setup and setup.exit:
            out.append(NeedRow(kind="slot_setup", project=p.id, bead=None,
                               why=f"slot {name}: setup failed (exit {setup.exit})", since=setup.t))
    out += [NeedRow(kind="stray", project=p.id, bead=x.ref if x.kind == "bead" else None, why=x.why, title=x.name)
            for x in p.strays]
    return out


def loop_rows(w: World, p: ProjectIn, info: LoopInfo) -> list[NeedRow]:
    if info.health == "absent":
        return [NeedRow(kind="absent", project=p.id, bead=None, since=info.last_activity,
                        why=f"{info.ready} ready bead(s) and no loop alive")]
    if info.health == "stalled":
        mins = int((w.now - (info.quiet_since or w.now)) // 60)
        return [NeedRow(kind="stalled", project=p.id, bead=None, since=info.quiet_since,
                        why=f"{info.ready} ready bead(s), nothing happened for {mins} min")]
    return []


def out_line(ln: LaneStatus) -> str:
    why = ln.out_reason or ln.reason
    return f"lane {ln.family or ln.label or ln.id} is out" + (f": {why}" if why else "")


def input_line(n: NeedInput) -> str:
    return f"delegate needs: {n.what}" + (f" ({n.why})" if n.why else "")


def lane_rows(w: World) -> list[NeedRow]:
    """A lane that is out (delegate's own reason: network, vendor wall, spend) and what delegate says it needs from the owner."""
    st = w.status
    if st is None:
        return []
    out = [NeedRow(kind="paused", project="", bead=None, until=ln.out_until, why=out_line(ln))
           for ln in st.lanes if state_of(ln, w.now - st.at) == "locked"]
    return out + [NeedRow(kind="paused", project="", bead=None, since=st.at, why=input_line(n)) for n in st.needs_input]


def needs_of(w: World, infos: Sequence[LoopInfo]) -> list[NeedRow]:
    """Every row, oldest first; a row with no recorded time goes last."""
    rows = lane_rows(w)
    for p in w.projects:
        info = next(i for i in infos if i.project == p.id)
        rows += [*bead_rows(w, p), *slot_rows(w, p), *loop_rows(w, p, info)]
    return sorted(rows, key=lambda r: (r.since is None, r.since or 0.0))
