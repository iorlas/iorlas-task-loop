"""The Live view's endpoints for the old dashboard server: /api/live and /api/live/overview over taskloop_dash. `srv` is the server
module (engine_logs, run_alive, task_spans ...), so this file imports nothing from it. Goes when server.py moves into the package."""
import os
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(HERE.parents[2] / "src"))
from taskloop_dash.api import live as live_api  # noqa: E402
from taskloop_dash.api import overview as overview_api  # noqa: E402
from taskloop_dash.views import names  # noqa: E402

LIVE_MAX = 24


class Globals:
    """A module's names by attribute, for a module that is not in sys.modules (tl loads server.py by path)."""

    def __init__(self, names_):
        self.names_ = names_

    def __getattr__(self, name):
        return self.names_[name]


class Live:
    def __init__(self, srv):
        self.srv, self.runs, self.lock = srv, {}, threading.Lock()

    def live_run(self, path):
        with self.lock:
            if path not in self.runs:
                while len(self.runs) >= LIVE_MAX:
                    self.runs.pop(next(iter(self.runs)))
                self.runs[path] = live_api.LiveRun(path)
            return self.runs[path]

    def alive(self, lr, path):
        """From the typed log alone (no pid probe): running until the close record, stale when nothing was written for STALE_RUN."""
        return lr.is_alive(time.time(), self.srv.STALE_RUN)

    def api_live(self, bead, run="", since="", before="", wait="0", limit="300"):
        """A bead's newest run (or the named one): its page of events, merged by time, with the state line. Without `since` the
        newest events and a `before` cursor; with it only what is new, held up to `wait` seconds."""
        s = self.srv
        s._last_seen[0] = time.time()
        if not names.is_bead_id(bead):
            return {"bead": bead, "found": False, "error": "not a bead id"}
        path = s.run_path(run) if run else None
        if run and not path:
            return {"bead": bead, "run": run, "found": False, "error": "no such run"}
        logs = s.engine_logs(retain=False).get(bead, [])
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
        return live_api.answer(lr, bead, newest, self.alive(lr, path), since or None, before or None, wait, limit)

    def entries(self):
        """The newest run of each bead that is alive or ended lately, as the overview takes them."""
        s, out = self.srv, []
        spans = s.task_spans()
        for bead, paths in s.engine_logs(retain=False).items():
            path = paths[-1]
            if time.time() - os.path.getmtime(path) > 2 * 3600:
                continue
            lr = self.live_run(path)
            lr.refresh()
            span = (spans.get(bead) or [None])[-1]
            out.append({"bead": bead, "repo": s.repo_name(span, None, None), "title": (span or {}).get("title") or "",
                        "name": names.run_name(path), "run": lr, "alive": self.alive(lr, path)})
        return out

    def queue_rows(self):
        """The slot line of every registered repo: who waits for a slot, first in line first."""
        s, rows = self.srv, []
        tl = s._tl()
        for repo in s.repos():
            for n, t in enumerate(tl.waiting_line(repo)):
                rows.append({"repo": os.path.basename(repo.rstrip("/\\")), "bead": t.get("bead") or "", "prio": t.get("prio"),
                             "since": t.get("t"), "ahead": n})
        return rows

    def api_live_overview(self, wait="0"):
        """A line per running, queued or paused bead and the lanes strip; held up to `wait` seconds until a log grows."""
        s = self.srv
        s._last_seen[0] = time.time()
        try:
            deadline = time.time() + min(float(wait or 0), 20.0)
        except ValueError:
            deadline = 0
        entries = self.entries()
        seen = [e["run"].sizes() for e in entries]
        while time.time() < deadline and seen == [e["run"].sizes() for e in entries]:
            time.sleep(0.25)
        entries = self.entries()
        lanes = s.cached("delegate-lanes", 20, lambda: s.delegate_status().get("lanes") or [])
        return overview_api.overview(entries, self.queue_rows(), lanes, time.time())
