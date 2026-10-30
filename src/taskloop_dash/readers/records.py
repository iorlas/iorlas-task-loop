"""The task-loop records the dash reads and never writes: the event index, registered repos, traces, engine logs, and the spans a
bead's claims make. Each is one file or folder under the config dir (taskloop.contracts.paths names them)."""

import glob
import json
import os
from dataclasses import dataclass
from typing import Any

from taskloop.contracts import wire
from taskloop.contracts.ids import BeadId
from taskloop.contracts.parks import Park
from taskloop.contracts.run import NetPause
from taskloop.contracts.runlife import RETAIN
from taskloop.contracts.stores import JsonStore, ReposStore
from taskloop.contracts.trace import RunTrace
from taskloop_dash.env import Env
from taskloop_dash.views import names
from taskloop_dash.views.world import Seen

Span = dict[str, Any]


@dataclass(frozen=True)
class TraceBook:
    """The retained traces by run, and how many lines of the file were not one this version reads."""
    runs: dict[str, RunTrace]
    skipped: int


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

    def seen_events(self) -> list[Seen]:
        """The events of the last week the needs list reads, as written: the writer (app/track/trail.event) sets no `v` and spells a kind
        `slot-hold`, so the strict contracts.events.decode would drop every row; only the fields the list uses are read."""
        out: list[Seen] = []
        for e in self.events():
            try:
                out.append(Seen(kind=str(e["kind"]).replace("-", "_"), t=float(e["t"]), bead=str(e.get("bead") or ""),
                                repo=str(e.get("repo") or ""),
                                why=str(e.get("why") or ""), until=float(e["until"]) if e.get("until") else None,
                                exit=int(e.get("exit") or 0), slot=str(e.get("slot") or "")))
            except (KeyError, TypeError, ValueError):
                continue
        return out

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

    def engine_logs(self, retain: bool = True) -> dict[BeadId, list[str]]:
        """bead -> its engine logs, oldest first."""
        cut = self.env.clock() - RETAIN if retain else 0
        out: dict[BeadId, list[str]] = {}
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

