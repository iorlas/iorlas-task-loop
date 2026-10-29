"""The test clock: time stands still until `advance`."""


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
