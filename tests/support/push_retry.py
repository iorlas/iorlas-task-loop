"""Test support for online push retries."""

from contextlib import contextmanager
from unittest import mock

from support.netgate import FakeProbe
from taskloop.adapters import halt
from taskloop.app.run import engine
from tltestkit.fake_clock import FakeClock


@contextmanager
def online_push_retries():
    """Keep push-failure retries online, with waits advancing test time instead of sleeping."""
    clock, probe = FakeClock(), FakeProbe([True])

    def nap(stopped, seconds):
        clock.advance(seconds)
        return stopped.is_set()

    with mock.patch.object(engine, "SystemClock", return_value=clock), mock.patch.object(halt, "nap", nap):
        yield probe, clock
