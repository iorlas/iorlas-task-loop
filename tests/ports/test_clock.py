"""The Clock port (contracts/ports.py): one contract on SystemClock and on FakeClock."""
from support.tags import contract

from tlkernel.ports import Clock
from tlkernel.systemclock import SystemClock
from tltestkit.fake_clock import FakeClock


class ClockContract:
    __test__ = False

    def make(self) -> Clock:
        raise NotImplementedError

    def test_now_is_a_float_of_epoch_seconds(self):
        clock = self.make()
        assert isinstance(clock.now(), float)
        assert clock.now() > 0

    def test_monotonic_is_a_float_that_never_goes_back(self):
        clock = self.make()
        first = clock.monotonic()
        assert isinstance(first, float)
        assert clock.monotonic() >= first


@contract
class TestSystemClock(ClockContract):
    __test__ = True
    def make(self) -> SystemClock:
        return SystemClock()


@contract
class TestFakeClock(ClockContract):
    __test__ = True
    def make(self) -> FakeClock:
        return FakeClock()

    def test_time_stands_still_until_advance_and_both_readings_move_together(self):
        clock = FakeClock()
        now, mono = clock.now(), clock.monotonic()
        assert (clock.now(), clock.monotonic()) == (now, mono)
        clock.advance(5)
        assert (clock.now() - now, clock.monotonic() - mono) == (5, 5)
