"""'Is the factory learning?' (dash-spec 7.1): weekly points from the ask ledger and the traces, by what is retained.

Weeks run Monday to Monday in local time, oldest first, the last one this week. The series starts at the week of the oldest ledger row
or landed run (at most 8 weeks back), so a week before the data is absent, never a zero. A week with nothing landed counts 0 for the
ratios. Honest limits: the ledger began with this backend, so the early weeks are short; `sendbacks_per_bead` is plan redos per landed
run (the traces keep replans, not look send-backs); `causes` counts asks only, since a stop's cause is bd metadata no history keeps."""
import time
from collections.abc import Sequence

from taskloop.contracts.dash import CauseCount, Learning, OwnerCause, Stick
from taskloop.contracts.ledger import LedgerEntry
from taskloop_dash.views.ledger import by_ask
from taskloop_dash.views.world import World

WEEK_S = 7 * 86400
WEEKS = 8
DURABLE = (Stick.ADR, Stick.REF, Stick.FACTORY, Stick.FIX, Stick.DEMOTE)


def week_start(t: float) -> float:
    """Local Monday 00:00 of the week `t` is in."""
    lt = time.localtime(t)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - lt.tm_wday, 0, 0, 0, 0, 0, -1))


def week_edges(first: float, now: float) -> list[float]:
    """The Mondays from the first data week (at most WEEKS back) to this week, oldest first. mktime keeps a DST week whole."""
    this = week_start(now)
    edges = [this]
    while len(edges) < WEEKS and edges[-1] > first:
        edges.append(week_start(edges[-1] - 3600))
    return edges[::-1]


def index_of(edges: Sequence[float], t: float) -> int | None:
    for k in range(len(edges) - 1, -1, -1):
        if t >= edges[k]:
            return k
    return None


def asks_of(w: World) -> list[tuple[LedgerEntry, LedgerEntry, bool]]:
    """(its raise row, its newest row, answered) per ask."""
    out = []
    for rs in by_ask(w.ledger).values():
        raised = next((r for r in rs if r.event == "raise"), None)
        if raised is not None:
            out.append((raised, rs[-1], any(r.event == "answer" for r in rs)))
    return out


def per(top: list[int], bottom: list[int]) -> list[float]:
    """top / bottom per week, 0 for a week with no bottom."""
    return [round(a / b, 2) if b else 0.0 for a, b in zip(top, bottom, strict=True)]


def build(w: World) -> Learning:
    asks = asks_of(w)
    firsts = [r.t for r, _, _ in asks] + [x.t for x in w.landings]
    if not firsts:
        return Learning()
    edges = week_edges(min(firsts), w.now)
    n = len(edges)
    raised, repeats, answered, durable = [0] * n, [0] * n, [0] * n, [0] * n
    landed, redos = [0] * n, [0] * n
    causes: list[dict[OwnerCause, int]] = [{} for _ in range(n)]
    for first, last, ok in asks:
        k = index_of(edges, first.t)
        if k is None:
            continue
        raised[k] += 1
        repeats[k] += bool(first.similar)
        causes[k][last.cause] = causes[k].get(last.cause, 0) + 1
        answered[k] += ok
        durable[k] += ok and last.outcome in DURABLE
    for x in w.landings:
        k = index_of(edges, x.t)
        if k is not None:
            landed[k] += 1
            redos[k] += x.replans

    now_c, prev_c = causes[-1], causes[-2] if n > 1 else {}
    return Learning(
        weeks=[time.strftime("%m-%d", time.localtime(e)) for e in edges], asks_per_landed=per(raised, landed), repeat_asks=repeats,
        sendbacks_per_bead=per(redos, landed), durable_pct=[round(100 * x, 1) for x in per(durable, answered)],
        causes=sorted((CauseCount(cause=c, now=now_c.get(c, 0), prev=prev_c.get(c, 0)) for c in {*now_c, *prev_c}),
                      key=lambda c: (-c.now, c.cause.value)))
