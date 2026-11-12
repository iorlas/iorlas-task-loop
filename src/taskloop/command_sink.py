"""The live sink of one agent run, display only. It notes the wall-clock time of the agent's latest command in the attempt's
evidence (`EvidenceFiles.note_command`, at most once a second) for `tl step list` and `show`, and appends every action of the
agent as one `any_agent.activity` line to the attempt's `events.jsonl` (`EvidenceFiles.open_events`) for the dashboard's lines.
A failed write is skipped, and nothing reads either for control."""

import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace

from any_agent import LiveSink, NullSink, RunHooks, events
from any_agent.activity import Timeline, encode

from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import CappedLog, EvidenceFiles

EVERY_S = 1.0


@dataclass(kw_only=True)
class WatchedHooks(RunHooks):
    """The attempt's run hooks plus the live sink of its run (`composition._run` hands it to the shelf's `run`)."""

    live: LiveSink = field(default_factory=NullSink)


class CommandSink:
    def __init__(self, files: EvidenceFiles, key: AttemptKey, clock: Callable[[], float],
                 tick: Callable[[], float] = time.monotonic) -> None:
        """`clock`: the wall time written; `tick`: the monotonic time the once-a-second throttle runs on."""
        self._files, self._key, self._clock, self._tick, self._last = files, key, clock, tick, float("-inf")
        self._timeline, self._lost = Timeline(), False
        self._run = f"{int(clock() * 1000)}:"  # a vendor restarts its ids with each process: a resumed run must not reuse the last one's
        self._events: CappedLog | None = None  # opened at the first action

    def started(self, pid: int) -> None:
        pass

    def _record(self, e: events.HarnessEvent) -> None:
        records = self._timeline.add(e, self._clock())
        if not records or self._lost:
            return
        try:
            if self._events is None:
                self._events = self._files.open_events(self._key)
            for record in records:
                scoped = record if record.id is None else replace(record, id=self._run + record.id)
                self._events.write((encode(scoped) + "\n").encode())
        except OSError:
            self._lost = True  # display only: no events file, no retry, never a failed attempt

    def feed(self, e: events.HarnessEvent) -> None:
        with suppress(Exception):
            self._record(e)
        if not isinstance(e, events.Cmd):
            return
        ticked = self._tick()
        if ticked - self._last < EVERY_S:
            return
        self._last = ticked
        with suppress(Exception):  # display only, and a live sink may not raise: a lost write never fails the attempt
            self._files.note_command(self._key, self._clock())

    def poll(self, idle_s: float) -> None:
        pass

    def end(self, status: str, cost_usd: float | None = None) -> None:
        if self._events is not None:
            with suppress(OSError):
                self._events.close()
            self._events = None
            self._lost = True
