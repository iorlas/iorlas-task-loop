"""The beads of a World as the page's cards: the facts of each bead gathered once, then column, marker, status, dots, totals."""

import statistics
from collections.abc import Sequence
from typing import Literal

from taskloop.contracts.ask import Ask
from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import BeadCard, Column, Marker, Phase, Totals
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.ids import BeadId, is_bead_id
from taskloop_dash.tails import parse_ts
from taskloop_dash.views import columns, names, passes, phases
from taskloop_dash.views.runfacts import Run
from taskloop_dash.views.world import ProjectIn, World

SLOT, LOOK = "slot", "owner-look"  # the labels of the loop's own beads: never cards
EPIC = "epic"
USUAL_MIN_N = 5  # a lane's usual is advisory (grey) until this many beads landed on it (dash-spec §2.6)
WATCH_AT, BAD_AT = 2, 4  # times the usual that turn a bead's tokens amber, then red
LOOP_STALE = 3 * 60.0  # a loop beats its state file every 60 s (LoopCfg.beat_every); three missed beats and it is gone
TotalsTone = Literal["", "watch", "bad", "grey"]


def is_infra(b: Bead) -> bool:
    return SLOT in b.labels or LOOK in b.labels


def is_work(b: Bead) -> bool:
    return not is_infra(b) and b.issue_type != EPIC


def when(iso: str) -> float | None:
    return parse_ts(iso) if iso else None


def blockers(b: Bead, by_id: dict[BeadId, Bead]) -> list[str]:
    """The ids of the open beads this one waits for (a `blocks` dependency), in bd's order."""
    out: list[str] = []
    for d in b.dependencies:
        dep = by_id.get(d.id) if is_bead_id(d.id) else None
        if d.type == "blocks" and dep is not None and dep.status != "closed":
            out.append(d.id)
    return out


def lane_of(runs: Sequence[Run]) -> str:
    return next((r.lane for r in reversed(runs) if r.lane), "")


def tone_of_totals(tokens: int, usual: int | None, n: int) -> TotalsTone:
    if usual is None or usual <= 0:
        return ""
    if n < USUAL_MIN_N:
        return "grey"
    return "bad" if tokens >= BAD_AT * usual else "watch" if tokens >= WATCH_AT * usual else ""


def ask_facts(a: Ask | None) -> tuple[bool, bool, str]:
    """(a blocking ask is open, a soft one is, its decision)."""
    if a is None or a.status not in (AskStatus.OPEN, AskStatus.PARKED) or a.consumed is not None or a.answer is not None:
        return False, False, ""
    return a.blocking, not a.blocking, a.decision


class Board:
    """Everything the cards of one World share: the work beads by project, each bead's passes, the lanes' usual tokens."""

    def __init__(self, w: World) -> None:
        self.w = w
        self.by_id = {p.id: {b.id: b for b in p.beads} for p in w.projects}
        self._passes: dict[str, list[passes.PassView]] = {}
        self.usual = self.usual_by_lane()

    def passes_of(self, bead: str) -> list[passes.PassView]:
        got = self._passes.get(bead)
        if got is None:
            got = self._passes[bead] = passes.passes_of(self.w.runs.get(bead, ()))
        return got

    def usual_by_lane(self) -> dict[str, tuple[int, int]]:
        """{lane: (median fresh tokens, beads)} over the beads whose newest run landed."""
        per: dict[str, list[int]] = {}
        for bead, runs in self.w.runs.items():
            lane = lane_of(runs)
            if lane and passes.landed(runs[-1]):
                per.setdefault(lane, []).append(passes.totals_of(self.passes_of(bead))[1])
        return {lane: (int(statistics.median(v)), len(v)) for lane, v in per.items()}

    def waits(self, p: ProjectIn) -> dict[str, str]:
        """{bead: why no slot takes it}, from the queue of a loop that runs now."""
        live = [s for s in p.loops if self.w.now - s.t < LOOP_STALE]
        newest = max(live, key=lambda s: s.t, default=None)
        return {r.bead: r.skip.why for r in newest.queue if r.skip} if newest else {}

    def card(self, p: ProjectIn, b: Bead, waits: dict[str, str]) -> BeadCard:
        runs = list(self.w.runs.get(b.id, ()))
        ps = self.passes_of(b.id)
        newest = runs[-1] if runs else None
        cur = newest.current() if newest else None
        ask_open, soft_ask, ask_line = ask_facts(self.w.asks.get(b.id))
        blocking = blockers(b, self.by_id[p.id])
        f = columns.Facts(
            closed=b.status == "closed", claimed=b.status == "in_progress", ask=ask_open, soft_ask=soft_ask,
            look=any(i.bead == b.id for i in p.looks),
            life=newest.life if newest else None, phase=cur.phase if cur else None, close=newest.close if newest else None,
            blocked=bool(blocking), ask_line=ask_line, step_text=cur.text if cur else "", wait=newest.wait if newest else None,
            blocker=blocking[0] if blocking else "", closed_reason=b.close_reason, assignee=b.assignee,
            stuck=bool(newest and newest.stuck), stuck_line=passes.stuck_text(newest.stuck) if newest and newest.stuck else "")
        col, mark = columns.column(f), columns.marker(f)
        visited = {s.phase for x in ps for s in x.spans if s.phase}
        current = Phase.LOOK if mark is Marker.LOOK else (cur.phase if cur else None)
        lane = lane_of(runs)
        return BeadCard(
            id=b.id, project=p.id, title=b.title, column=col, marker=mark, status=columns.status_line(f), tone=columns.tone_of(mark),
            t=self.entered(f, b, newest), epic=b.parent if b.parent in self.by_id[p.id] else None,
            slot=(newest.slot or None) if newest and col is not Column.BACKLOG else None, lane=lane or None,
            loops=sum(1 for x in ps if x.end in phases.LOOPED), dots=columns.dots_of(visited, current, mark, f.closed),
            needs=blocking,  # the snapshot drops the ids it trimmed away
            waits_why=waits.get(b.id, "") if col is Column.BACKLOG else "", totals=self.totals(ps, lane),
            shots=len(self.shots(runs)), assumptions=sum(r.assumed for r in runs))

    @staticmethod
    def entered(f: columns.Facts, b: Bead, newest: Run | None) -> float | None:
        """When the bead came into its state: the run's start while it runs, its Close when parked, bd's own times otherwise."""
        if f.closed:
            return when(b.closed_at) or when(b.updated_at)
        if newest and f.open_run:
            return newest.t0
        if newest and newest.close and f.close and not f.claimed:
            return newest.close.t
        return when(b.updated_at) or when(b.created_at)

    def totals(self, ps: list[passes.PassView], lane: str) -> Totals:
        if not ps:
            return Totals()
        secs, tokens = passes.totals_of(ps)
        usual, n = self.usual.get(lane, (None, 0))
        return Totals(secs=secs, tokens=tokens, usual=usual, usual_n=n, tone=tone_of_totals(tokens, usual, n))

    @staticmethod
    def shots(runs: Sequence[Run]) -> set[str]:
        """The pictures the bead's runs left (names the engine recorded in its Artifacts records)."""
        return {n for r in runs for a in r.artifacts for n in a.names if names.kind_of(n) == "image"}

