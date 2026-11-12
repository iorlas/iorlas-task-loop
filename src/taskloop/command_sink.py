"""The live sink of one agent run: notes the wall-clock time of the agent's latest command in the attempt's evidence
(`EvidenceFiles.note_command`) for `tl step list` and `show`. Display only: written at most once a second, a failed write
is skipped, and nothing reads it for control."""

import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field

from any_agent import LiveSink, NullSink, RunHooks, events

from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import EvidenceFiles

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

    def started(self, pid: int) -> None:
        pass

    def feed(self, e: events.HarnessEvent) -> None:
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
        pass
