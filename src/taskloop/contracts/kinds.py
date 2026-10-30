"""The closed set of ways a run ends (`Kind`) and the sealed `Fault` union over the ones that did not finish. Lives in contracts so the
dashboard and the report read a stored run's end by the same types the engine wrote it with; the policy table is domain/outcome."""

import enum
from dataclasses import dataclass
from typing import ClassVar, Final, assert_never, final


class Kind(enum.Enum):
    LANDED = "landed"
    DONE = "done"
    CUT = "cut"  # trial cell cut short; no production code raises it
    ASK_DECISION = "ask_decision"
    ASK_STUCK = "ask_stuck"
    ASK_BUDGET = "ask_budget"
    ASK_TICKET = "ask_ticket"
    WAIT_ASK = "wait_ask"  # an ask is still open: nothing new is asked or said
    PAUSE_LANE = "pause_lane"
    PAUSE_NETWORK = "pause_network"
    PAUSE_KILLED = "pause_killed"
    OWNER_PARK = "owner_park"  # the owner parked it (a park request): the branch and checkpoint stay, the hold keeps the loop off
    FAULT_INFRA = "fault_infra"
    FAULT_SLOT = "fault_slot"
    FAULT_DENIED = "fault_denied"
    FAULT_STALE_BASE = "fault_stale_base"
    FAULT_PLAN = "fault_plan"
    FAULT_LAND = "fault_land"
    FAULT_ENGINE = "fault_engine"
    FAULT_BAD_REQUEST = "fault_bad_request"
    FAULT_CONTRACT_SKEW = "fault_contract_skew"
    FAULT_BASE_RED = "fault_base_red"
    FAULT_CRASHED = "fault_crashed"


FINISH: Final = (Kind.LANDED, Kind.DONE)
ASKS: Final = tuple(k for k in Kind if k.name.startswith("ASK_"))
PAUSES: Final = tuple(k for k in Kind if k.name.startswith("PAUSE_"))
FAULTS: Final = tuple(k for k in Kind if k.name.startswith("FAULT_"))


ASK_NAME: Final = {Kind.ASK_DECISION: "decision", Kind.ASK_STUCK: "stuck", Kind.ASK_BUDGET: "budget", Kind.ASK_TICKET: "ticket"}


class Action(enum.Enum):
    """What the close does with a run that did not finish: the one action of each Fault variant."""
    RETRY = "retry"  # leave the bead open and unassigned: the machine's trouble clears, the bead is run again
    ASK = "ask"      # block the bead and put one question to the owner
    HOLD = "hold"    # the owner holds it (a park, an ask still open): nothing new is asked or said


@final
@dataclass(frozen=True)
class Infra:
    """The machine's trouble (a fault, a pause): not the task's."""
    kind: Kind
    action: ClassVar[Action] = Action.RETRY


@final
@dataclass(frozen=True)
class Task:
    """The task needs a decision only the owner can give (an ask)."""
    kind: Kind
    action: ClassVar[Action] = Action.ASK


@final
@dataclass(frozen=True)
class Owner:
    """The owner's own act is the reason (a park, an open ask)."""
    kind: Kind
    action: ClassVar[Action] = Action.HOLD


Fault = Infra | Task | Owner
_OWNER_KINDS: Final = (Kind.OWNER_PARK, Kind.WAIT_ASK)


def fault_of(kind: Kind) -> Fault | None:
    """The Fault variant of a kind; None for a finish (LANDED, DONE)."""
    if kind in FINISH:
        return None
    if kind in ASKS:
        return Task(kind)
    if kind in _OWNER_KINDS:
        return Owner(kind)
    return Infra(kind)


def action_of(fault: Fault) -> Action:
    match fault:
        case Infra() | Task() | Owner():
            return fault.action
        case _:
            assert_never(fault)


def kind_named(value: str) -> Kind | None:
    """The Kind a stored kind word names; None for "" or a word this version has no Kind for (never a guess)."""
    try:
        return Kind(value)
    except ValueError:
        return None
