"""/api/live and /api/live/overview for the server: one LiveRun per run kept between polls (each poll reads only what the files gained),
and the entries the overview takes (the newest run of each bead that is alive or ended lately)."""

import os
import threading
import time
from typing import Any

from taskloop.contracts import codec
from taskloop.contracts.runlife import Liveness
from taskloop_dash.api import live as live_api
from taskloop_dash.api import overview as overview_api
from taskloop_dash.api.lanes import Lanes
from taskloop_dash.api.tasks import repo_name
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import basename
from taskloop_dash.readers.records import Records
from taskloop_dash.views import live_lines, names

LIVE_MAX = 24  # runs kept open
RECENT = 2 * 3600  # a run that ended longer ago is not on the overview
MAX_WAIT = 20.0


class Live:
    def __init__(self, env: Env, records: Records, lanes: Lanes) -> None:
        self.env, self.records, self.lanes = env, records, lanes
        self.runs: dict[str, live_api.LiveRun] = {}
        self.lock = threading.Lock()

    def live_run(self, path: str) -> live_api.LiveRun:
        with self.lock:
            if path not in self.runs:
                while len(self.runs) >= LIVE_MAX:
                    self.runs.pop(next(iter(self.runs)))
                self.runs[path] = live_api.LiveRun(path)
            return self.runs[path]

    def api_live(
        self, bead: str, run: str = "", since: str = "", before: str = "", wait: str | float = "0", limit: str | int = "300"
    ) -> dict[str, Any]:
        """A bead's newest run (or the named one): its page of events, merged by time, with the state line. Without `since` the newest
        events and a `before` cursor; with it only what is new, held up to `wait` seconds."""
        self.env.touch()
        if not names.is_bead_id(bead):
            return {"bead": bead, "found": False, "error": "not a bead id"}
        path = self.records.run_path(run) if run else None
        if run and not path:
            return {"bead": bead, "run": run, "found": False, "error": "no such run"}
        logs = self.records.engine_logs(retain=False).get(bead, [])
        if not path:
            if not logs:
                return {"bead": bead, "found": False, "error": "no engine run for this bead"}
            path = logs[-1]
        lr = self.live_run(path)
        try:
            wait, limit = float(wait or 0), int(limit or 300)
        except ValueError:
            wait, limit = 0.0, 300
        lr.refresh()
        newest = names.run_name((logs or [path])[-1])
        now = self.env.clock()
        return live_api.answer(lr, bead, newest, lr.liveness(now), since or None, before or None, wait, limit, now=now)

    def api_v2_live(self, bead: str, since: str = "", wait: str | float = "0") -> tuple[int, dict[str, Any]]:
        """GET /api/v2/live: the bead's newest run as a typed LivePage. Without `since` the newest events, with it only what is new, held up
        to `wait` seconds until a file grows. 404 for a bead with no run. The same LiveRun and cursor as /api/live."""
        self.env.touch()
        logs = self.records.engine_logs(retain=False).get(bead, []) if names.is_bead_id(bead) else []
        if not logs:
            return 404, {"error": "no engine run for this bead"}
        lr = self.live_run(logs[-1])
        try:
            hold = float(wait or 0)
        except ValueError:
            hold = 0.0
        lr.refresh()
        cursor = live_api.decode(since or None)
        got = live_api.poll(lr, cursor, hold)
        return 200, codec.to_json(live_lines.page(got["events"], got["cursor"], lr.liveness(self.env.clock())))

    def entries(self) -> list[dict[str, Any]]:
        """The newest run of each bead that is alive or ended lately, as the overview takes them."""
        out = []
        spans = self.records.task_spans()
        for bead, paths in self.records.engine_logs(retain=False).items():
            path = paths[-1]
            if self.env.clock() - os.path.getmtime(path) > RECENT:
                continue
            lr = self.live_run(path)
            lr.refresh()
            span = (spans.get(bead) or [None])[-1]
            out.append({"bead": bead, "repo": repo_name(span, None, None), "title": (span or {}).get("title") or "",
                        "name": names.run_name(path), "run": lr, "alive": lr.liveness(self.env.clock()) is Liveness.LIVE})
        return out

    def queue_rows(self) -> list[dict[str, Any]]:
        """The slot line of every registered repo: who waits for a slot, first in line first."""
        rows = []
        for repo in self.records.repos():
            for n, t in enumerate(self.env.ports.waiting_line(repo)):
                rows.append({"repo": basename(repo), "bead": t.bead, "why": t.why, "prio": t.prio, "since": t.since, "ahead": n})
        return rows

    def api_live_overview(self, wait: str | float = "0") -> dict[str, Any]:
        """A line per running, queued or paused bead and the lanes strip; held up to `wait` seconds until a log grows."""
        self.env.touch()
        try:
            deadline = time.time() + min(float(wait or 0), MAX_WAIT)
        except ValueError:
            deadline = 0
        entries = self.entries()
        seen = [e["run"].sizes() for e in entries]
        while time.time() < deadline and seen == [e["run"].sizes() for e in entries]:
            time.sleep(0.25)
        entries = self.entries()
        lanes = self.env.ttl.get("delegate-lanes", 20, lambda: self.lanes.delegate_status().get("lanes") or [])
        return overview_api.overview(entries, self.queue_rows(), lanes, self.env.clock())
