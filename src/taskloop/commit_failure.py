"""The factory commit's refusals as `Failed`: one kind per result, an uncommitted listing as the detail."""

from typing import Final

from taskloop.attempt_types import CommitRefused, CommitWaiting, NotApplicable, Rejected, Uncommitted, waiting_reason
from taskloop.operation_failure import Failed, FailureKind
from taskloop.step_text import unsafe_details

WAITING: Final[FailureKind] = "waiting"
UNCOMMITTED: Final[FailureKind] = "uncommitted"
COMMIT_KINDS: Final[dict[type[Rejected | NotApplicable | CommitRefused | Uncommitted | CommitWaiting], FailureKind]] = {
    Rejected: "rejected",
    NotApplicable: "not_applicable",
    CommitRefused: "refused",
    Uncommitted: UNCOMMITTED,
    CommitWaiting: WAITING,
}


def commit_failure(result: Rejected | NotApplicable | CommitRefused | Uncommitted | CommitWaiting) -> Failed:
    """Uncommitted files carry their listing (`bounded` where it was read) as the detail, as `tl attempt show` prints it."""
    if isinstance(result, (Uncommitted, CommitRefused)):
        details = (
            (unsafe_details(result),)
            if isinstance(result, Uncommitted)
            else ("Contradictory retained facts: inconsistent verdict or end commit.",)
            if result.reason == "inconsistent"
            else ()
        )
        return Failed(COMMIT_KINDS[type(result)], result.reason, "\n".join(filter(None, (*details, "\n".join(result.listing)))))
    reason = (
        result.what if isinstance(result, NotApplicable) else waiting_reason(result) if isinstance(result, CommitWaiting) else result.reason
    )
    return Failed(COMMIT_KINDS[type(result)], reason)
