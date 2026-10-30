"""A stored run end, read once at the edge: the engine log's Close record as the Fault it names (taskloop.contracts.kinds), or
nothing when this version cannot say which it is. Past this module no view compares an outcome word or reads a prose `why`."""

import dataclasses
import enum
from typing import Final, assert_never

from taskloop.contracts.enums import Outcome, WhyCode
from taskloop.contracts.kinds import Fault, Infra, Kind, Owner, Task
from taskloop.contracts.log import Close

TAKES_OUT: Final = frozenset({Outcome.LANDED, Outcome.DONE})  # a close that finished the task: no fault
HELD: Final = frozenset({Outcome.BLOCKED, Outcome.PARKED})  # a close that left the task with the owner or the clock

# What a close's why_code says, the inverse of app/run/trace.WHY_CODE up to the fault kinds a view cannot tell apart (every
# FAULT_* but the three named reads as a failure; tests/dash/test_dash_closes.py holds the two tables together).
BY_CODE: Final[dict[WhyCode, Fault]] = {
    WhyCode.OWNER_DECISION: Task(Kind.ASK_DECISION),
    WhyCode.STUCK: Task(Kind.ASK_STUCK),
    WhyCode.OVER_BUDGET: Task(Kind.ASK_BUDGET),
    WhyCode.TICKET: Task(Kind.ASK_TICKET),
    WhyCode.PAUSED: Owner(Kind.OWNER_PARK),
    WhyCode.LANE_OUT: Infra(Kind.PAUSE_LANE),
    WhyCode.NETWORK: Infra(Kind.PAUSE_NETWORK),
    WhyCode.STOPPED_BY_COORDINATOR: Infra(Kind.PAUSE_KILLED),
    WhyCode.GATE_RED: Infra(Kind.FAULT_BASE_RED),
    WhyCode.SCHEMA_INVALID: Infra(Kind.FAULT_BAD_REQUEST),
    WhyCode.CHECK_BEFORE_LAND: Infra(Kind.FAULT_LAND),
    WhyCode.FAILED: Infra(Kind.FAULT_INFRA),
}


class End(enum.Enum):
    """How a run ended, as the dashboard tells it: one word per way."""
    FINISHED = "finished"
    ASKED = "asked"
    WAITING = "waiting"
    PAUSED = "paused"
    PARKED = "parked"
    STOPPED = "stopped"
    FAILED = "failed"


def end_of(fault: Fault | None) -> End:
    match fault:
        case None:
            end = End.FINISHED
        case Task():
            end = End.ASKED
        case Owner(kind=Kind.WAIT_ASK):
            end = End.WAITING
        case Owner():
            end = End.PARKED
        case Infra(kind=Kind.PAUSE_KILLED):
            end = End.STOPPED
        case Infra(kind=Kind.PAUSE_LANE | Kind.PAUSE_NETWORK | Kind.CUT):
            end = End.PAUSED
        case Infra():
            end = End.FAILED
        case _:
            assert_never(fault)
    return end


def fault_of_code(close: Close) -> Fault | None:
    """The Fault an unfinished close names by its why_code; None when no kind of this version writes that pair."""
    code = close.why_code
    if code is WhyCode.NEEDS_HUMAN:  # the same code for an open ask (held) and a refused worker (a failure)
        return Owner(Kind.WAIT_ASK) if close.outcome in HELD else Infra(Kind.FAULT_DENIED)
    return BY_CODE.get(code) if code is not None else None


@dataclasses.dataclass(frozen=True)
class Ended:
    """A run's close read for a view: how it ended, and the engine's own words for it."""
    end: End
    fault: Fault | None
    outcome: Outcome
    why: str
    sha: str


def read(close: Close) -> Ended | None:
    """None when the close is not one this version writes (no why_code on a run that did not finish, a code no kind maps to)."""
    if close.outcome in TAKES_OUT:
        return Ended(End.FINISHED, None, close.outcome, close.why, close.sha)
    fault = fault_of_code(close)
    return Ended(end_of(fault), fault, close.outcome, close.why, close.sha) if fault is not None else None
