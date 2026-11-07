"""RetryPlan: the remaining ways the engine tries a worker step again, as rows. A row says how many retries the step gets
and whether exhaustion faults or asks. `policy.decide` reads the recovery limits
and the worker_failed exhaustion action; the app's `WorkerCall` reads validation
and denial limits. Delegate owns retries within a worker call.

    invalid_output   the answer broke its schema: again, on a new thread
    denied_read      the guard refused only read-only commands: once more on a fresh thread told what was refused
    denied_secret    a write was denied for `secrets` on a heredoc whose body names `.env`: once more with the apply_patch note
    resume_refused   the vendor refused the ref a call resumed: one new thread with the whole prompt, then the fault
    worker_failed    a resumed worker failed: one fresh engine prompt, rerouting hurt writes
"""

from dataclasses import dataclass
from typing import Final, Literal

Then = Literal["fault", "ask"]


@dataclass(frozen=True)
class RetryRow:
    kind: str
    limit: int  # retries after the first call
    then: Then = "fault"  # what the step does when the retries are spent
    note: str = ""


ROWS: Final = (
    RetryRow("invalid_output", 1, then="fault", note="answer broke its schema"),
    RetryRow("denied_read", 1, then="fault", note="read-only commands refused"),
    RetryRow("denied_secret", 1, then="fault", note="a heredoc body named .env"),
    RetryRow("resume_refused", 1, then="fault", note="the vendor refused the ref to resume"),
    RetryRow("worker_failed", 1, then="ask", note="worker failed, timed out or was killed"),
)
KINDS: Final = tuple(r.kind for r in ROWS)


class RetryPlan:
    """Engine recovery limits, with fault/ask exhaustion for a failed worker."""

    def __init__(self, rows: tuple[RetryRow, ...] = ROWS) -> None:
        self.rows = {r.kind: r for r in rows}

    def row(self, kind: str) -> RetryRow:
        return self.rows[kind]

    def left(self, kind: str, used: int) -> bool:
        """Another retry of `kind` is allowed after `used` of them."""
        return used < self.rows[kind].limit


PLAN: Final = RetryPlan()
