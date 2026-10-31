"""The task-loop records the dash reads and never writes: the event index, registered repos, traces, engine logs, and the spans a
bead's claims make. Each is one file or folder under the config dir (taskloop.contracts.paths names them)."""

import json
import os
from dataclasses import dataclass
from typing import Any

from taskloop.contracts import events, runlife, wire
from taskloop.contracts.events import Event
from taskloop.contracts.ids import BeadId
from taskloop.contracts.locator import RunBundle, RunLocator
from taskloop.contracts.parks import Park
from taskloop.contracts.run import NetPause
from taskloop.contracts.runlife import RETAIN
from taskloop.contracts.stores import JsonStore, ReposStore
from taskloop.contracts.trace import RunTrace
from taskloop_dash.env import Env

Span = dict[str, Any]


@dataclass(frozen=True)
class TraceBook:
    """The retained traces by run, and how many lines of the file were not one this version reads."""
    runs: dict[str, RunTrace]
    skipped: int


class Records:
    def __init__(self, env: Env) -> None:
        self.env = env
        self.locator = RunLocator(env.config)

    def events(self) -> list[Event]:
        """The events of the last week, re-read when the file changes. A row that is not an Event of this version (an older `v`, an
        unknown kind, bad JSON) is skipped, never read as something it is not."""
        cut = self.env.clock() - RETAIN

        def load(path: str) -> list[Event]:
            out: list[Event] = []
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for ln in fh:
                        try:
                            e = events.decode(json.loads(ln))
                        except ValueError:
                            continue
                        if e.t >= cut:
                            out.append(e)
            except OSError:
                pass
            return out
        return self.env.files.get(str(self.env.config.events()), load, [])

    def parks(self) -> dict[str, Park]:
        """bead -> its Park record (left by runs that ended on a question; the loop skips the bead while its text is the same)."""
        folder = self.env.config.park(BeadId("x")).parent
        found = (JsonStore(f, Park).get() for f in sorted(folder.glob("*.json")))
        return {r.bead: r for r in found if r is not None}

    def net_pauses(self) -> dict[str, NetPause]:
        """bead -> the NetPause a run left when it paused for the network and no run has taken up yet."""
        folder = self.env.config.net_pause(BeadId("x")).parent
        found = (JsonStore(f, NetPause).get() for f in sorted(folder.glob("*.json")))
        return {r.bead: r for r in found if r is not None}

    def repos(self) -> list[str]:
        known = ReposStore(self.env.config).known()
        return [p for p in known if os.path.isdir(p)]

    def traces(self) -> TraceBook:
        """run -> its RunTrace, re-read when the file changes. A line that is not a RunTrace of this version (an older `v`, bad
        JSON) is skipped and counted, never read as something it is not."""
        def load(path: str) -> TraceBook:
            runs: dict[str, RunTrace] = {}
            skipped = 0
            for ln in self.env.tails.tail_lines(path, 20_000_000):
                try:
                    t = wire.load(RunTrace, json.loads(ln))
                except ValueError:
                    skipped += 1
                    continue
                runs[str(t.run)] = t
            return TraceBook(runs, skipped)
        return self.env.files.get(str(self.env.config.traces()), load, TraceBook({}, 0))

    def engine_logs(self, retain: bool = True) -> dict[BeadId, list[RunBundle]]:
        """bead -> its runs that have an engine log, oldest first (the locator's order); `retain`: only the logs written lately."""
        now = self.env.clock()
        runlife.reconcile(self.env.config, now)  # a run whose process is gone is marked lost here, once; the readers only read the state
        cut = now - RETAIN if retain else 0
        out: dict[BeadId, list[RunBundle]] = {}
        for b in self.locator.runs():
            try:
                if os.path.getmtime(b.log) < cut:
                    continue
            except OSError:
                continue
            out.setdefault(BeadId(b.bead), []).append(b)
        return out
