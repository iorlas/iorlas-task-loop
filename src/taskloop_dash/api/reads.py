"""Polled resources (snapshot, bead, cost): typed builder records in the contracts wire form. Each resource's content-hash
`version` is its ETag: a request that already holds it (`since=` or If-None-Match) gets a 304 and no body."""

import json
from dataclasses import replace
from typing import Any

from taskloop.contracts import wire
from taskloop.contracts.dash import BeadDetail, Snapshot
from taskloop.contracts.dashcost import CostPage
from taskloop.contracts.ids import BeadId, is_bead_id
from taskloop_dash.env import Env
from taskloop_dash.readers.world import Worlds
from taskloop_dash.refresh import RefreshCache
from taskloop_dash.views import bead_detail, cost, snapshot
from taskloop_dash.views.board import Board
from taskloop_dash.views.runfacts import Run
from taskloop_dash.views.world import World

SNAPSHOT_TTL = 3.0  # at least the page's polling interval
Reply = tuple[int, bytes, dict[str, str]]


def encode(rec: Any) -> bytes:
    return json.dumps(wire.dump(rec), separators=(",", ":")).encode("utf-8")


def etag(version: str) -> str:
    return f'"{version}"'


def versioned(rec: Snapshot | BeadDetail | CostPage, q: dict[str, str], held: str | None) -> Reply:
    """All polled resources use the same content hash and conditional response."""
    version = snapshot.version_of(rec)
    headers = {"ETag": etag(version)}
    if (q.get("since") or (held or "").strip('"')) == version:
        return 304, b"", headers
    return 200, encode(rec.replace(version=version)), headers


class Reads:
    def __init__(self, env: Env, worlds: Worlds) -> None:
        self.env, self.worlds = env, worlds
        self.cache: RefreshCache[tuple[World, Snapshot]] = RefreshCache(env.clock)
        self.details: RefreshCache[BeadDetail | None] = RefreshCache(env.clock)

    def wait(self) -> None:
        self.details.wait()
        self.cache.wait()

    def built(self) -> tuple[World, Snapshot]:
        """Publish a snapshot and its source world atomically."""
        def build() -> tuple[World, Snapshot]:
            world = self.worlds.world()
            return world, snapshot.build(world)
        if self.worlds.database_error():
            return build()
        return self.cache.get("snapshot", SNAPSHOT_TTL, build)

    def snapshot(self) -> Snapshot:
        self.env.touch()
        return self.built()[1]

    def bead(self, project: str, bead: str) -> BeadDetail | None:
        """The drawer of one bead; None for a bead no project of the machine lists."""
        self.env.touch()
        path = self.worlds.repos().get(project)
        if path is None or not is_bead_id(bead):
            return None
        if self.worlds.database_error():
            return self._bead(project, bead, path)
        return self.details.get(f"bead:{project}:{bead}", SNAPSHOT_TTL, lambda: self._bead(project, bead, path))

    def _bead(self, project: str, bead: BeadId, path: str) -> BeadDetail | None:
        w, _ = self.built()
        p = next((x for x in w.projects if x.id == project), None)
        b = next((x for x in p.beads if x.id == bead), None) if p else None
        if p is None or b is None:
            return None
        runs = self.worlds.bead_runs(path, bead)
        w = replace(w, now=self.env.clock(), runs={**w.runs, (project, bead): runs})
        newest: Run | None = runs[-1] if runs else None
        comments = self.worlds.comments(path, bead)
        bd_ok_at, bd_error = self.worlds.beads.health(path, bead)
        return bead_detail.build(Board(w), p, b, comments, self.worlds.live_events(newest),
                                 self.worlds.stage_events(runs)).replace(bd_ok_at=bd_ok_at, bd_error=bd_error)

    def cost(self, window: str, last: int, project: str) -> CostPage:
        self.env.touch()
        if self.worlds.database_error():
            return cost.build(self.worlds.world(), window, last, project)
        return self.env.ttl.get(f"cost:{window}:{last}:{project}", SNAPSHOT_TTL,
                                lambda: cost.build(self.worlds.world(), window, last, project))

    def get(self, path: str, q: dict[str, str], if_none_match: str | None = None) -> Reply:
        """(status, body, extra headers) of a polled resource GET."""
        if path == "/api/snapshot":
            return versioned(self.snapshot(), q, if_none_match)
        if path == "/api/bead":
            if not q.get("project") or not q.get("id"):
                return 400, b'{"error": "project and id"}', {}
            detail = self.bead(q["project"], q["id"])
            return versioned(detail, q, if_none_match) if detail else (404, b'{"error": "no such bead"}', {})
        if path == "/api/cost":
            window, last = q.get("window", "24h"), q.get("last", "0")
            ok = window in cost.WINDOWS and last.isdigit()
            bad = (400, b'{"error": "window 24h|7d, last a number"}', {})
            return versioned(self.cost(window, int(last), q.get("project", "")), q, if_none_match) if ok else bad
        return 404, b'{"error": "not found"}', {}
