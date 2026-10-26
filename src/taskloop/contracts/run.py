"""Run records: what a run-task process reports to its loop, and the hand-over between two engine versions."""
from dataclasses import field
from typing import ClassVar

from taskloop.contracts.codec import record
from taskloop.contracts.enums import Outcome, WhyCode


@record
class RunOutcome:
    """The last line run-task prints and loop/<key>/<bead>-<stamp>.outcome.json."""

    V: ClassVar[int] = 2
    outcome: Outcome
    bead: str
    run: str
    why_code: WhyCode | None = None
    why: str = ""
    log: str = ""
    minutes: float = 0.0
    rounds: int = 0
    tests_added: int = 0
    asked: bool = False
    retry_after: float | None = None
    cost: float = 0.0


@record
class LoopLogLine:
    """A line of loop/<key>.jsonl: the outcome plus where it ran."""

    V: ClassVar[int] = 2
    outcome: RunOutcome
    t: float
    slot: str | None = None
    run_log: str = ""


@record
class Reexec:
    """runs/<run>/reexec.json: the one record an old process writes and a newer install reads (TL_REEXEC)."""

    V: ClassVar[int] = 1
    run: str
    bead: str
    from_version: str
    to_version: str
    step: str
    owned: list[str] = field(default_factory=list)
    fallback: str = ""
    counters: dict[str, int] = field(default_factory=dict)
