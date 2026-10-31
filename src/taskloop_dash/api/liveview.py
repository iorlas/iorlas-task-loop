"""GET /api/live for the server: one LiveRun per run kept between polls, so each poll reads only what the files gained."""

import threading
from typing import Any

from taskloop.contracts import wire
from taskloop.contracts.ids import is_bead_id
from taskloop.contracts.locator import RunBundle
from taskloop_dash.api import live as live_api
from taskloop_dash.env import Env
from taskloop_dash.readers.records import Records
from taskloop_dash.views import live_lines

LIVE_MAX = 24  # runs kept open


class Live:
    def __init__(self, env: Env, records: Records) -> None:
        self.env, self.records = env, records
        self.runs: dict[str, live_api.LiveRun] = {}
        self.lock = threading.Lock()

    def live_run(self, b: RunBundle) -> live_api.LiveRun:
        path = b.run
        with self.lock:
            if path not in self.runs:
                while len(self.runs) >= LIVE_MAX:
                    self.runs.pop(next(iter(self.runs)))
                self.runs[path] = live_api.LiveRun(b)
            return self.runs[path]

    def page(self, bead: str, since: str = "", wait: str | float = "0") -> tuple[int, dict[str, Any]]:
        """The bead's newest run as a typed LivePage. Without `since` the newest events, with it only what is new, held up to `wait`
        seconds until a file grows. 404 for a bead with no run."""
        self.env.touch()
        logs = self.records.engine_logs(retain=False).get(bead, []) if is_bead_id(bead) else []
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
        return 200, wire.dump(live_lines.page(got["events"], got["cursor"], lr.liveness(self.env.clock())))
