"""The Snapshot (GET /api/snapshot): everything the four tabs read, built from one World.

Filled from typed facts: server, projects, epics, slots, every bead card (its assumptions and stuck marker included), the Floor's
pieces, the open asks and looks, the ask ledger, the decisions in force, the learning series and the lane cards (views.lanecards).
Left at their default until the backend item that records the fact: on a card the cause and ack only. `version` is a hash of the
encoded snapshot without `t`, so it moves exactly when a field the page shows moves."""

import hashlib
import json
import time

from taskloop.contracts import wire
from taskloop.contracts.ask import FACTORY_NOTICE_RUN
from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import AskCard, BeadCard, BeadDetail, Column, Epic, Piece, Project, ServerInfo, Slot, Snapshot
from taskloop.contracts.dashcost import CostPage
from taskloop_dash.views import floor, learning, ledger, needs, passes, queue
from taskloop_dash.views.askcards import ask_card, look_card, stale_of
from taskloop_dash.views.board import Board, is_infra, is_work, when
from taskloop_dash.views.lanecards import lane_cards
from taskloop_dash.views.world import ProjectIn, World

BACKLOG_MAX = 200


def midnight(now: float) -> float:
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def epics_of(p: ProjectIn) -> list[Epic]:
    """Only bd's epic type makes an epic; done/total count its children."""
    work = [b for b in p.beads if is_work(b)]
    out: list[Epic] = []
    for e in p.beads:
        kids = [b for b in work if b.parent == e.id]
        if e.issue_type == "epic" and not is_infra(e):
            out.append(Epic(id=e.id, project=p.id, title=e.title,
                            open=e.status != "closed" and (not kids or any(b.status != "closed" for b in kids)),
                            done=sum(1 for b in kids if b.status == "closed"), total=len(kids)))
    return out


def shown(b: Bead, since: float) -> bool:
    """Open beads, and closed ones since local midnight."""
    return b.status != "closed" or (when(b.closed_at) or 0.0) >= since


def cards_of(w: World, board: Board) -> tuple[list[BeadCard], int]:
    cards: list[BeadCard] = []
    backlog: list[tuple[int, BeadCard]] = []
    since = midnight(w.now)
    for p in w.projects:
        waits = board.waits(p)
        for b in p.beads:
            if is_work(b) and shown(b, since):
                c = board.card(p, b, waits)
                if c.column is Column.BACKLOG:
                    backlog.append((b.priority if b.priority is not None else 2, c))
                else:
                    cards.append(c)
    backlog.sort(key=lambda x: x[0])
    return cards + [c for _, c in backlog[:BACKLOG_MAX]], max(0, len(backlog) - BACKLOG_MAX)


def pieces_of(w: World, board: Board, ids: set[tuple[str, str]]) -> list[Piece]:
    out: list[Piece] = []
    for p in w.projects:
        for b in p.beads:
            key = (p.id, b.id)
            if key in ids and key in w.runs:
                out += [x for x in passes.pieces_of(p.id, b.id, w.runs[key], board.passes_of(key)) if floor.in_window(x, w.now)]
    return out


def asks_of(w: World, cards: list[BeadCard]) -> list[AskCard]:
    """The open asks and looks, whole; a look is as old as its bead's state (no clock enters a card: the version would never hold)."""
    ids = {(c.project, c.id): c.t or 0.0 for c in cards}
    out: list[AskCard] = []
    for p in w.projects:
        for b in p.beads:
            a = w.asks.get((p.id, b.id))
            if a is not None and (p.id, b.id) in ids:
                out.append(ask_card(p.id, a, ledger.similar_of(a, p, w), stale_of(a, p)))
        out += [look_card(p.id, i, ids[(p.id, i.bead)]) for i in p.looks if (p.id, i.bead) in ids]
        out += [ask_card(p.id, a) for (project, _bead), a in w.asks.items()
                if project == p.id and a.run == FACTORY_NOTICE_RUN and (p.id, a.bead) not in ids]
    return out


def slots_of(w: World) -> list[Slot]:
    out: list[Slot] = []
    for p in w.projects:
        runs = {b: rs for (key, b), rs in w.runs.items() if key == p.id}
        out += [*floor.slots_of(p, runs, w.now), *floor.stray_rows(p)]
    return out


def build(w: World) -> Snapshot:
    board = Board(w)
    cards, more = cards_of(w, board)
    ids = {(c.project, c.id) for c in cards}
    cards = [c.replace(needs=[n for n in c.needs if (c.project, n) in ids]) for c in cards]
    loops = [needs.health(w, p) for p in w.projects]
    server = ServerInfo(version=w.version, host=w.host, loops=loops)
    if w.database_error:
        server = server.replace(database_error=w.database_error)
    snap = Snapshot(
        version="", t=0.0, server=server,
        needs=needs.needs_of(w, loops), runs=sorted(w.run_headers, key=lambda r: r.started, reverse=True)[:10],
        adhoc=sorted((r for r in w.run_headers if not r.bead and r.state.live), key=lambda r: r.started, reverse=True),
        leases=list(w.leases),
        queue=[x for p in w.projects for x in queue.items_of(w, p)],
        projects=[Project(id=p.id, name=p.name, profile_error=p.profile_error,
                          bd_ok_at=p.bd_ok_at, bd_error=p.bd_error) for p in w.projects],
        epics=[e for p in w.projects for e in epics_of(p)],
        slots=slots_of(w), beads=cards, backlog_more=more, pieces=pieces_of(w, board, ids), asks=asks_of(w, cards),
        lanes=lane_cards(w.status, w.now), ledger=ledger.ledger_rows(w, ids), adrs=ledger.adr_rows(w), learning=learning.build(w))
    return snap.replace(version=version_of(snap), t=w.now)


def version_of(snap: Snapshot | CostPage | BeadDetail) -> str:
    """A resource's content hash, excluding its build time and the token itself."""
    body = json.dumps(wire.dump(snap.replace(version="", t=0.0)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]
