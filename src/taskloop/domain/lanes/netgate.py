"""The network seam: a probe, the gate a paused run waits on, and the loop's offline detector (tl-7y6.2.13, tl-kyy).

`NetProbe.up()` answers True, False, or None (unknown: the probe could not run). The production adapter is
`adapters.delegate.RouteProbe` (delegate's `route.py net`: sockets only, no model call, no quota); FakeProbe scripts answers for tests.
`NetState` is the loop's detector: a PAUSE_NETWORK close sets it down (one `down` transition), then it probes every
PROBE_EVERY seconds while down (one `up` transition). Unknown never holds a loop down: it reads as "go and see" after the
probe gap. No sockets of its own.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

PROBE_EVERY = 60  # seconds between probes while the network is down (tl-kyy: about every minute)


class NetProbe(Protocol):
    def up(self) -> bool | None: ...


class FakeProbe:
    """A script of answers, one per up() call; the last one repeats. calls counts the probes made."""

    def __init__(self, script: Sequence[bool | None]) -> None:
        self.script, self.calls = list(script), 0

    def up(self) -> bool | None:
        a = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return a


@dataclass
class NetState:
    """down_since: wall time the network was first seen down (None: up). next_probe: when to look again."""

    down_since: float | None = None
    next_probe: float = 0.0
    polls: int = 0

    @property
    def down(self) -> bool:
        return self.down_since is not None

    def mark_down(self, now: float) -> bool:
        """A PAUSE_NETWORK close. True only for the transition (the one `net_down` event)."""
        if self.down:
            return False
        self.down_since, self.next_probe, self.polls = now, now, 0
        return True

    def poll(self, probe: NetProbe, now: float) -> str | None:
        """-> "up" (the transition: the one `net_up` event; the state is cleared), or None. Probes at most every PROBE_EVERY.
        An unknown probe (None) counts as up once the first gap has passed: a loop is never held by a broken probe."""
        if not self.down or now < self.next_probe:
            return None
        self.polls += 1
        a = probe.up()
        if a is None and self.down_since is not None and now - self.down_since < PROBE_EVERY:
            a = False
        if a is False:
            self.next_probe = now + PROBE_EVERY
            return None
        self.down_since, self.next_probe = None, 0.0
        return "up"
