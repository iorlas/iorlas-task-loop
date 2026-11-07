"""Close admission rules, independent of storage and land adapters."""
from collections.abc import Callable
from typing import Final

from tlkernel.ids import BeadId

GATED: Final = ("task", "feature", "bug")
FREE: Final = ("duplicate", "wontfix", "superseded", "epic")
MANUAL: Final = "manual-landed-with-sha:"


def reason_head(reason: str) -> str:
    return reason.strip().split(None, 1)[0].rstrip(":,;.") if reason.strip() else ""


def manual_sha(reason: str) -> str:
    """The sha a `manual-landed-with-sha:<sha> ...` reason names; "" for any other reason."""
    head = reason.strip().split(None, 1)[0] if reason.strip() else ""
    return head.removeprefix(MANUAL) if head.startswith(MANUAL) else ""


def fix(bead: str) -> str:
    return (f"tl land {bead} --sha SHA   (when the work is on the base), or: "
            f"tl task close {bead} --reason 'manual-landed-with-sha:<sha> <why>', or a typed reason: "
            f"tl task close {bead} --reason 'duplicate|wontfix|superseded|epic <why>'")



def refusal(bead: BeadId, reason: str, issue_type: str | None, *,
            has_land: Callable[[], bool], has_work: Callable[[], bool], manual: Callable[[str], str]) -> str:
    """Return a refusal, checking and recording a manual land only when needed."""
    if issue_type not in GATED or reason_head(reason) in FREE:
        return ""
    if sha := manual_sha(reason):
        return manual(sha)
    if has_land() or not has_work():
        return ""
    return f"{bead} has an engine run or a task branch and no land on record: not closed. Fix: " + fix(bead)
