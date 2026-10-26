"""The clock seam: SystemClock in production, FakeClock in tests. Stdlib only."""

import time


class SystemClock:
    def now(self):
        return time.time()

    def monotonic(self):
        return time.monotonic()


class FakeClock:
    def __init__(self, start=1_000_000.0):
        self.t = float(start)

    def now(self):
        return self.t

    def monotonic(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds
        return self.t
