"""Time, tokens and cost per stage and bead (GET /api/cost): sums over the engine logs the dashboard already reads.

Nothing here is estimated or recounted: a step's time is its StepEnd.exec_seconds, a call's tokens and cost are its CallEnd's, a wait's its
WaitEnd's. A cost the worker's answer did not give (`cost_source` unknown) is counted in `unknown` and left out of `cost`. A run is in
the window when its newest record is."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from taskloop.contracts.dashcost import CostPage, CostRow
from taskloop_dash.views import phases
from taskloop_dash.views.runfacts import Call, Run
from taskloop_dash.views.world import World

WINDOWS: Final = {"24h": 86400.0, "7d": 7 * 86400.0}


@dataclass
class Sum:
    secs: float = 0.0
    tokens: int = 0
    cost: float = 0.0
    calls: int = 0
    unknown: int = 0

    def call(self, c: Call) -> None:
        self.tokens += c.tokens
        self.calls += 1
        if c.cost_known:
            self.cost += c.cost
        else:
            self.unknown += 1


Buckets = dict[str, Sum]


def stage_of(step: str) -> str:
    ph = phases.phase_of(step)
    return ph.value if ph else step


def rows(b: Mapping[str, Sum], bead: str = "") -> list[CostRow]:
    ranked = sorted(b.items(), key=lambda kv: (-kv[1].secs, kv[0]))
    return [CostRow(key=k, secs=round(v.secs), tokens=v.tokens, cost=round(v.cost, 4), calls=v.calls, unknown=v.unknown, bead=bead)
            for k, v in ranked]


def in_scope(w: World, window: str, last: int, project: str) -> list[tuple[str, Run]]:
    ids = {b.id for p in w.projects if not project or p.id == project for b in p.beads}
    every = [(bead, r) for bead, rs in w.runs.items() if bead in ids for r in rs]
    if last > 0:
        return sorted(every, key=lambda x: -x[1].last_t)[:last]
    since = w.now - WINDOWS[window]
    return [x for x in every if x[1].last_t >= since]


def span_secs(r: Run) -> Iterable[tuple[str, float]]:
    for s in r.spans:
        yield stage_of(s.step), s.secs if s.t1 is not None else max(0.0, r.end_of(s) - s.t0)


def build(w: World, window: str = "24h", last: int = 0, project: str = "") -> CostPage:
    stages, beads, waits = Buckets(), Buckets(), Buckets()
    drill: dict[str, Buckets] = {}
    picked = in_scope(w, window, last, project)
    for bead, r in picked:
        mine = drill.setdefault(bead, {})
        for stage, secs in span_secs(r):
            for into in (stages, mine):
                into.setdefault(stage, Sum()).secs += secs
            beads.setdefault(bead, Sum()).secs += secs
        for c in r.calls:
            stage = stage_of(c.step)
            for into, key in ((stages, stage), (mine, stage), (beads, bead)):
                into.setdefault(key, Sum()).call(c)
        for x in r.waits:
            waits.setdefault(x.what, Sum()).secs += x.secs
    out = CostPage(t=w.now, window="last" if last > 0 else window, runs=len(picked), stages=rows(stages),
                   beads=rows(beads), waits=rows(waits))
    return out.replace(drill=[x for bead in sorted(drill) for x in rows(drill[bead], bead)])

