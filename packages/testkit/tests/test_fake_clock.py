"""Injected clocks advance deterministically without sleeping."""
from tltestkit.fake_clock import FakeClock, SteppingClock


def test_advance_moves_now_and_monotonic():
    clock = FakeClock(start=10)
    assert clock.now() == clock.monotonic() == 10
    assert clock.advance(5) == 15
    assert clock.now() == clock.monotonic() == 15


def test_stepping_clock_advances_on_each_read():
    clock = SteppingClock(step=2, start=10)
    assert clock() == 12
    assert clock() == 14
