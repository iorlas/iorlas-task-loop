"""Round: what a block of checks has decided so far, and a lane's stop flag."""
import threading
from dataclasses import dataclass, field

from taskloop.contracts.checks import CheckResult


class Cancel(threading.Event):
    """A lane's stop flag: set when another lane went red first; `red` says which check."""

    red: str = ""


@dataclass
class Round:
    """What a round has decided so far."""

    n: int  # the round's number in the run
    results: list[CheckResult] = field(default_factory=list)
    by_step: dict[int, CheckResult] = field(default_factory=dict)
    red: str = ""  # the group of the first red: later groups, and every expensive check, are skipped
    red_skipped: set[int] = field(default_factory=set)  # steps left out because of a red
    env: dict[str, str] = field(default_factory=dict)  # $TL_CHECK_LOG_/RC_<ID> of what ran, for the checks after it
    timings: list[tuple[str, float]] = field(default_factory=list)  # (command, secs) of what passed, for the duration history
    changed: list[str] | None = None
    cancel: Cancel | None = None  # a lane's flag: set when another lane went red first
