"""The task-loop records the dash reads and never writes: the event index, registered repos, traces, engine logs, and the spans a
bead's claims make. Each is one file or folder under the config dir (taskloop.contracts.paths names them)."""

import glob
import json
import os
from typing import Any

from taskloop.contracts.runlife import RETAIN
from taskloop.contracts.stores import ReposStore
from taskloop_dash.env import Env
from taskloop_dash.views import names

Span = dict[str, Any]


class Records:
    def __init__(self, env: Env) -> None:
        self.env = env

    def events(self) -> list[dict[str, Any]]:
        """events.jsonl rows of the last week, re-read when the file changes."""
        cut = self.env.clock() - RETAIN

        def load(path: str) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for ln in fh:
                        try:
                            e = json.loads(ln)
                        except ValueError:
                            continue
                        if isinstance(e, dict) and e.get("t", 0) >= cut:
                            out.append(e)
            except OSError:
                pass
            return out
        return self.env.files.get(str(self.env.config.events()), load, [])

    def repos(self) -> list[str]:
        known = ReposStore(self.env.config).known()
        return [p for p in known if os.path.isdir(p)]

    def traces(self) -> dict[str, dict[str, Any]]:
        """run -> its traces.jsonl line, re-read when the file changes."""
        def load(path: str) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for ln in self.env.tails.tail_lines(path, 20_000_000):
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("run"):
                    out[r["run"]] = r
            return out
        return self.env.files.get(str(self.env.config.traces()), load, {})

    def engine_logs(self, retain: bool = True) -> dict[str, list[str]]:
        """bead -> its engine logs, oldest first."""
        cut = self.env.clock() - RETAIN if retain else 0
        out: dict[str, list[str]] = {}
        for p in glob.glob(str(self.env.config.engine_log("*"))):
            bead = names.bead_of(names.run_name(p))
            if not bead:
                continue
            try:
                if os.path.getmtime(p) < cut:
                    continue
            except OSError:
                continue
            out.setdefault(bead, []).append(p)
        for v in out.values():
            v.sort()
        return out

