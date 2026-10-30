"""The network seam: a probe and a scripted one for tests (tl-7y6.2.13, tl-kyy).

`NetProbe.up()` answers True, False, or None (unknown: the probe could not run). The production adapter is
`adapters.delegate.RouteProbe` (delegate's `route.py net`: sockets only, no model call, no quota); FakeProbe scripts answers for tests.
The loop's offline detector is app/loop/net.py. No sockets of its own.
"""

from collections.abc import Sequence
from typing import Final, Protocol

PROBE_EVERY: Final = 60  # seconds between probes while the network is down (tl-kyy: about every minute)


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
