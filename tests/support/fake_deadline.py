"""A fake monotonic clock and bounded event wait for deadline tests; nothing sleeps or sends a signal."""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from taskloop.adapters import deadline
from tltestkit.fake_clock import FakeClock


class FakeEvent:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock

    def wait(self, timeout: float | None = None) -> bool:
        assert timeout is not None
        self.clock.advance(timeout)
        return False


class FakeDeadline:
    def __init__(self) -> None:
        self.clock = FakeClock()

    def wait(self, seconds: float) -> None:
        deadline.wait(seconds, FakeEvent(self.clock).wait)

    def patched(self) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(mock.patch.object(deadline, "time", SimpleNamespace(monotonic=self.clock.monotonic)))
        return stack
