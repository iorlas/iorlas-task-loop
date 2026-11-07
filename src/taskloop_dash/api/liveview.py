"""GET /api/live for the server: one LiveRun per run kept between polls, so each poll reads only what the files gained."""

import threading
from typing import Any

from taskloop_dash.api import live as live_api
from taskloop_dash.env import Env
from taskloop_dash.readers import dbruns
from taskloop_dash.readers.records import Records
from taskloop_dash.views import live_lines
from tlkernel import wire
from tlkernel.ids import is_bead_id, loop_key
from tlkernel.runlife import shown

LIVE_MAX = 24  # runs kept open


class Live:
    def __init__(self, env: Env, records: Records) -> None:
        self.env, self.records = env, records
        self.runs: dict[str, live_api.LiveRun] = {}
        self.lock = threading.Lock()

    def live_run(self, path: str) -> live_api.LiveRun:
        with self.lock:
            if path not in self.runs:
                while len(self.runs) >= LIVE_MAX:
                    self.runs.pop(next(iter(self.runs)))
                self.runs[path] = live_api.LiveRun(self.env.config, path)
            return self.runs[path]

    def page(self, project: str, bead: str, since: str = "", wait: str | float = "0") -> tuple[int, dict[str, Any]]:
        """The bead's newest run as a typed LivePage. Without `since` the newest events, with it only what is new, held up to `wait`
        seconds until a file grows. 404 for a bead with no run."""
        self.env.touch()
        rows, error = dbruns.read(self.env.config, self.env.clock(), bead=bead)
        if error:
            return 503, {"error": error}
        logs = [r for r in rows if loop_key(r.manifest.repo) == project and r.has_log] if is_bead_id(bead) else []
        if not logs:
            return 404, {"error": "no engine run for this bead"}
        lr = self.live_run(logs[-1].manifest.run)
        try:
            hold = float(wait or 0)
        except ValueError:
            hold = 0.0
        got = lr.read(since, hold)
        state = shown(logs[-1].manifest, self.env.clock())
        return 200, wire.dump(live_lines.page(got["events"], got["cursor"], state, got.get("reset", False), got.get("gap", False)))
