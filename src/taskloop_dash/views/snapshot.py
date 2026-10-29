"""The Snapshot (GET /api/snapshot): everything the four tabs read, built from one World.

Filled from typed facts: server, projects, epics, slots, every bead card (its assumptions and stuck marker included), the Floor's
pieces, the open asks and looks, the ask ledger, the decisions in force, the learning series and the lane cards (views.lanecards).
Left at their default until the backend item that records the fact: on a card the cause and ack only. `version` is a hash of the
encoded snapshot without `t`, so it moves exactly when a field the page shows moves."""

import dataclasses
import hashlib
import json
import time

from taskloop.contracts import codec
from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import AskCard, BeadCard, Column, Epic, LoopInfo, Piece, Project, ServerInfo, Slot, Snapshot
from taskloop_dash.views import floor, learning, ledger, passes
from taskloop_dash.views.askcards import ask_card, look_card, stale_of
from taskloop_dash.views.board import LOOP_STALE, Board, is_infra, is_work, when
from taskloop_dash.views.lanecards import lane_cards
from taskloop_dash.views.world import ProjectIn, World

BACKLOG_MAX = 200


def midnight(now: float) -> float:
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def epics_of(p: ProjectIn) -> list[Epic]:
    """An epic is a bead other beads name as their parent (or one bd types `epic`); done/total count its children."""
    work = [b for b in p.beads if is_work(b)]
    out: list[Epic] = []
    for e in p.beads:
        kids = [b for b in work if b.parent == e.id]
        if kids and not is_infra(e):
            out.append(Epic(id=e.id, project=p.id, title=e.title, done=sum(1 for b in kids if b.status == "closed"), total=len(kids)))
    return out


def loop_info(p: ProjectIn, now: float) -> LoopInfo:
    beat = max((s.t for s in p.loops), default=None)
    return LoopInfo(project=p.id, running=beat is not None and now - beat < LOOP_STALE, last_activity=beat)


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
            if (p.id, b.id) in ids and b.id in w.runs:
                out += [x for x in passes.pieces_of(p.id, b.id, w.runs[b.id], board.passes_of(b.id)) if floor.in_window(x, w.now)]
    return out


def asks_of(w: World, cards: list[BeadCard]) -> list[AskCard]:
    """The open asks and looks, whole; a look is as old as its bead's state (no clock enters a card: the version would never hold)."""
    ids = {(c.project, c.id): c.t or 0.0 for c in cards}
    out: list[AskCard] = []
    for p in w.projects:
        for b in p.beads:
            a = w.asks.get(b.id)
            if a is not None and (p.id, b.id) in ids:
                out.append(ask_card(p.id, a, ledger.similar_of(a, p, w), stale_of(a, p)))
        out += [look_card(p.id, i, ids[(p.id, i.bead)]) for i in p.looks if (p.id, i.bead) in ids]
    return out


def slots_of(w: World) -> list[Slot]:
    return [floor.slot_of(p, b, w.runs, w.now) for p in w.projects for b in p.slots]


def build(w: World) -> Snapshot:
    board = Board(w)
    cards, more = cards_of(w, board)
    ids = {(c.project, c.id) for c in cards}
    cards = [dataclasses.replace(c, needs=[n for n in c.needs if (c.project, n) in ids]) for c in cards]
    snap = Snapshot(
        version="", t=0.0, server=ServerInfo(version=w.version, host=w.host, loops=[loop_info(p, w.now) for p in w.projects]),
        projects=[Project(id=p.id, name=p.name) for p in w.projects], epics=[e for p in w.projects for e in epics_of(p)],
        slots=slots_of(w), beads=cards, backlog_more=more, pieces=pieces_of(w, board, ids), asks=asks_of(w, cards),
        lanes=lane_cards(w.status, w.now), ledger=ledger.ledger_rows(w, ids), adrs=ledger.adr_rows(w), learning=learning.build(w))
    return dataclasses.replace(snap, version=version_of(snap), t=w.now)


def version_of(snap: Snapshot) -> str:
    """A hash of the snapshot as encoded, `t` left out: it changes when anything the page shows changes."""
    body = json.dumps(codec.to_json(dataclasses.replace(snap, version="", t=0.0)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]
