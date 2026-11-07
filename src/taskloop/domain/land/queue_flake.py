"""One retry, then clean main: attribute queue reds without ejecting known flakes (design section 7)."""
from collections.abc import Sequence
from enum import StrEnum
from typing import Final, final

from taskloop.contracts.wire import Rec
from taskloop.domain.checks.retry import retry_allowed

WEEK_S: Final = 7 * 86400


@final
class Attempt(Rec):
    rc: int
    out: str


class Verdict(StrEnum):
    RETRY = "retry"
    MAIN = "main"
    BLAME = "blame"
    FLAKE = "flake"
    MAIN_RED = "main_red"


def decide(red: Attempt, retry: Attempt | None, main: Attempt | None, *, retried: bool) -> Verdict:
    """Request at most one retry, then main; a skipped retry is recorded by `retried`."""
    if retry is not None and retry.rc == 0:
        return Verdict.FLAKE
    if main is not None:
        return Verdict.MAIN_RED if main.rc != 0 else Verdict.BLAME
    if retry is None and not retried and red.rc != 124 and retry_allowed(1, 1, red.out):
        return Verdict.RETRY
    return Verdict.MAIN


@final
class FlakeRow(Rec):
    test: str
    t: float
    how: str
    run: str = ""
    bead: str = ""


def row(test: str, t: float, verdict: Verdict, retry: Attempt | None) -> FlakeRow | None:
    """Log retry recovery or a failure reproduced on main, once the verdict is known."""
    if verdict is Verdict.FLAKE:
        return FlakeRow(test=test, t=t, how="retry")
    if verdict is Verdict.MAIN_RED:
        return FlakeRow(test=test, t=t, how="main")
    return None


def score(rows: Sequence[FlakeRow], test: str, now: float, week_s: float = WEEK_S) -> int:
    """Count this test's events in the inclusive week, excluding future events."""
    return sum(r.test == test and now - week_s <= r.t <= now for r in rows)
