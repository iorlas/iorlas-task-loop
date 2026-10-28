"""RetryPlan: the six ways the engine tries a worker step again, as rows. A row says how many retries the step gets, how long
it rests before each, and what happens when they are spent. Nothing else in the engine counts a retry: `policy.decide` and the
app's `WorkerCall` read these rows, so changing a limit is changing one line here.

    invalid_output   the answer broke its schema: again, on a new thread
    denied_read      the guard refused only read-only commands: once more on a fresh thread told what was refused
    denied_secret    a write was denied for `secrets` on a heredoc whose body names `.env`: once more with the apply_patch note
    lane_poll        busy, vendor_blip, duplicate task: poll a few times, then another lane
    crash            delegate itself died: again after each rest, then a fault
    worker_failed    the worker failed or timed out (or its lane exited -15): another lane once, then one ask
"""

from dataclasses import dataclass
from typing import Final, Literal

Then = Literal["fault", "ask", "reroute", "pause"]


@dataclass(frozen=True)
class RetryRow:
    kind: str
    limit: int  # retries after the first call
    rests: tuple[float, ...] = ()  # seconds before retry i (the last repeats); () = at once
    then: Then = "fault"  # what the step does when the retries are spent
    note: str = ""


ROWS: Final = (
    RetryRow("invalid_output", 1, then="fault", note="answer broke its schema"),
    RetryRow("denied_read", 1, then="fault", note="read-only commands refused"),
    RetryRow("denied_secret", 1, then="fault", note="a heredoc body named .env"),
    RetryRow("lane_poll", 3, rests=(20.0,), then="reroute", note="lane busy or blipping"),
    RetryRow("crash", 2, rests=(30.0, 120.0), then="fault", note="delegate died"),
    RetryRow("worker_failed", 1, then="ask", note="worker failed, timed out or was killed"),
)
KINDS: Final = tuple(r.kind for r in ROWS)


class RetryPlan:
    def __init__(self, rows: tuple[RetryRow, ...] = ROWS) -> None:
        self.rows = {r.kind: r for r in rows}

    def row(self, kind: str) -> RetryRow:
        return self.rows[kind]

    def left(self, kind: str, used: int) -> bool:
        """Another retry of `kind` is allowed after `used` of them."""
        return used < self.rows[kind].limit

    def rest(self, kind: str, used: int) -> float:
        """Seconds to rest before retry number `used` (from 0)."""
        rests = self.rows[kind].rests
        return rests[min(used, len(rests) - 1)] if rests else 0.0


PLAN: Final = RetryPlan()
