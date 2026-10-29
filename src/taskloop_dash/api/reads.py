"""The reads (GET /api/snapshot, GET /api/bead): typed records from the builders, encoded by the contracts codec. The snapshot's
`version` is its ETag: a request that already holds it (`since=` or If-None-Match) gets a 304 and no body."""

import json
from typing import Any

from taskloop.contracts import codec
from taskloop.contracts.dash import BeadDetail, Snapshot
from taskloop_dash.env import Env
from taskloop_dash.readers.world import Worlds
from taskloop_dash.views import bead_detail, names, snapshot
from taskloop_dash.views.board import Board
from taskloop_dash.views.runfacts import Run

SNAPSHOT_TTL = 1.0  # seconds one built snapshot answers every poll
Reply = tuple[int, bytes, dict[str, str]]


def encode(rec: Any) -> bytes:
    return json.dumps(codec.to_json(rec), separators=(",", ":")).encode("utf-8")


def etag(version: str) -> str:
    return f'"{version}"'


class Reads:
    def __init__(self, env: Env, worlds: Worlds) -> None:
        self.env, self.worlds = env, worlds

    def snapshot(self) -> Snapshot:
        self.env.touch()
        return self.env.ttl.get("snapshot", SNAPSHOT_TTL, lambda: snapshot.build(self.worlds.world()))

    def bead(self, project: str, bead: str) -> BeadDetail | None:
        """The drawer of one bead; None for a bead no project of the machine lists."""
        self.env.touch()
        path = self.worlds.repos().get(project)
        if path is None or not names.is_bead_id(bead):
            return None
        w = self.worlds.world(full=bead)
        p = next((x for x in w.projects if x.id == project), None)
        b = next((x for x in p.beads if x.id == bead), None) if p else None
        if p is None or b is None:
            return None
        runs = w.runs.get(bead, [])
        newest: Run | None = runs[-1] if runs else None
        return bead_detail.build(Board(w), p, b, self.worlds.comments(path, bead), self.worlds.live_events(newest))

    def get(self, path: str, q: dict[str, str], if_none_match: str | None = None) -> Reply:
        """(status, body, extra headers) of a GET of /api/snapshot or /api/bead."""
        if path == "/api/snapshot":
            snap = self.snapshot()
            held = q.get("since") or (if_none_match or "").strip('"')
            if held == snap.version:
                return 304, b"", {"ETag": etag(snap.version)}
            return 200, encode(snap), {"ETag": etag(snap.version)}
        if path == "/api/bead":
            if not q.get("project") or not q.get("id"):
                return 400, b'{"error": "project and id"}', {}
            detail = self.bead(q["project"], q["id"])
            return (200, encode(detail), {}) if detail else (404, b'{"error": "no such bead"}', {})
        return 404, b'{"error": "not found"}', {}
