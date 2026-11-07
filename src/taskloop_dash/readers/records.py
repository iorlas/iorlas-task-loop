"""The task-loop records the dash reads and never writes: the event index, registered repos, traces, engine logs, and the spans a
bead's claims make. Each is one file or folder under the config dir (tlkernel.paths names them)."""

import json
import os
from dataclasses import dataclass

from taskloop_dash.env import Env
from tlkernel import events, wire
from tlkernel.events import Event
from tlkernel.parks import Park, ParkStore
from tlkernel.rowstores import ReposStore
from tlkernel.run import NetPause
from tlkernel.runlife import RETAIN
from tlkernel.trace import RunTrace
from tlkernel.waitrows import NET_PAUSE, open_records


@dataclass(frozen=True)
class TraceBook:
    """The retained traces by run, and how many lines of the file were not one this version reads."""
    runs: dict[str, RunTrace]
    skipped: int


class Records:
    def __init__(self, env: Env) -> None:
        self.env = env

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
        return ParkStore.open_parks(self.env.config)

    def net_pauses(self) -> dict[str, NetPause]:
        """bead -> the NetPause a run left when it paused for the network and no run has taken up yet."""
        return open_records(self.env.config, NET_PAUSE, NetPause)

    def repos(self) -> list[str]:
        known = ReposStore(self.env.config, quiet=True).known()
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
