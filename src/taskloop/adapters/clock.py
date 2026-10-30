"""The clock seam: SystemClock in production (FakeClock, tests/support/fake_clock.py, in tests)."""

import time


class SystemClock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()
