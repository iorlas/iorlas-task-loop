"""The gates in flight of one repo's merge queue and the gate seconds it wasted (docs/design/merge-queue.md section 6). One `InFlight`
per repo, so a flaky repo does not shrink another's speculation. The numbers are the queue's to read; this holds no gate and merges
nothing, and nothing calls it until the queue builder does."""
from collections import deque

from taskloop.domain.land.queue_in_flight import DEFAULT_CAP, WASTE_LAST_MERGES, Account, Cause, Event, in_flight, wasted_ratio


class InFlight:
    def __init__(self, cap: int = DEFAULT_CAP) -> None:
        self.cap, self.current = cap, 1
        self.accounts: deque[Account] = deque(maxlen=WASTE_LAST_MERGES)
        self.pending_s: float = 0.0  # wasted seconds since the last merge, and why
        self.pending_causes: list[Cause] = []

    @property
    def ratio(self) -> float:
        return wasted_ratio(self.accounts)

    def waste(self, seconds: float, cause: Cause) -> None:
        """A gate that was cancelled or invalidated, `seconds` long."""
        self.pending_s += seconds
        self.pending_causes.append(cause)

    def merged(self, pr: int, useful_gate_s: float) -> int:
        """A PR landed: its account (the useful seconds and the waste since the merge before) enters the ratio, then G grows or holds."""
        self.accounts.append(Account(pr=pr, useful_gate_s=useful_gate_s, wasted_gate_s=self.pending_s, causes=tuple(self.pending_causes)))
        self.pending_s = 0.0
        self.pending_causes = []
        return self.happened(Event.MERGED)

    def happened(self, event: Event) -> int:
        self.current = in_flight(self.current, event, cap=self.cap, ratio=self.ratio)
        return self.current
