"""The live sink of one agent run, display only. It appends every action as one `any_agent.activity` line to the attempt's
`events.jsonl` (`EvidenceFiles.open_events`), shared by the CLI's last-command age and the dashboard's activity lines.
A failed write is skipped, and nothing reads the stream for control."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field

from any_agent import LiveSink, NullSink, RunHooks, events
from any_agent.activity import Timeline, encode

from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import CappedLog, EvidenceFiles


@dataclass(kw_only=True)
class WatchedHooks(RunHooks):
    """The attempt's run hooks plus the live sink of its run (`composition._run` hands it to the shelf's `run`)."""

    live: LiveSink = field(default_factory=NullSink)


class CommandSink:
    def __init__(
        self, files: EvidenceFiles, key: AttemptKey, clock: Callable[[], float], observe: Callable[[], None] = lambda: None,
    ) -> None:
        """`clock`: the wall time written for each observed action."""
        self._files, self._key, self._clock = files, key, clock
        self._observe = observe
        # a vendor restarts its ids with each process: a resumed run's scope keeps it from reusing the last run's
        self._timeline, self._lost = Timeline(f"{int(clock() * 1000)}:"), False
        self._events: CappedLog | None = None  # opened at the first action

    def started(self, pid: int) -> None:
        self._observe()

    def _record(self, e: events.HarnessEvent) -> None:
        records = self._timeline.add(e, self._clock())
        if not records or self._lost:
            return
        try:
            if self._events is None:
                self._events = self._files.open_events(self._key)
            for record in records:
                self._events.write((encode(record) + "\n").encode())
        except OSError:
            self._lost = True  # display only: no events file, no retry, never a failed attempt

    def feed(self, e: events.HarnessEvent) -> None:
        self._observe()
        with suppress(Exception):  # display only: a lost write never fails the attempt
            self._record(e)

    def poll(self, idle_s: float) -> None:
        self._observe()

    def end(self, status: str, cost_usd: float | None = None) -> None:
        self._observe()
        if self._events is not None:
            with suppress(OSError):
                self._events.close()
            self._events = None
            self._lost = True
