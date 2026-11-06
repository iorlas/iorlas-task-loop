"""The test clock: time stands still until `advance`."""

import threading


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.t = float(start)

    def now(self) -> float:
        return self.t

    def monotonic(self) -> float:
        return self.t

    def advance(self, seconds: float) -> float:
        self.t += seconds
        return self.t


class SteppingClock:
    """A monotonic clock for a run with a real child: time moves only when somebody looks (every read adds `step`), so a silence or a grace
    that takes minutes to a real worker takes a few polls of the supervisor. Thread-safe."""

    def __init__(self, step: float, start: float = 1_000_000.0) -> None:
        self.t, self.step = float(start), step
        self.lock = threading.Lock()

    def __call__(self) -> float:
        with self.lock:
            self.t += self.step
            return self.t
