"""What the land's steps share: its counters between tries, and the words for where a try stands."""
from dataclasses import dataclass
from enum import Enum

PUSH_UP_FAILS = 3  # network errors on the push while the probe says the network is up: not the network's to cure (a proxy, DNS)
PUSH_TRIES = 3  # a push rejected because main moved is tried again this often


class Phase(Enum):
    """Where the land stands between its tries (one state, not two flags)."""

    FRESH = "fresh"
    STEP_OPEN = "step open"  # the outside gate's land step is still open: the lock's first try goes on in it
    NET_DOWN = "net down"  # the last push died of the network: look again before pushing


class Placing(Enum):
    """Where the gate runs for the push in the lock."""

    NO_GATE = ""
    CACHED = "cached"  # it passed on this tree and base
    STALE = "stale"  # main moved under the outside gate: let the lock go, gate outside again
    INSIDE = "inside"  # the tries are used up: gate here, as a busy main must not starve a bead
    OUTSIDE = "outside"


class Next(Enum):
    """What a push that did not land asks of the land."""

    AGAIN = "again"  # rejected: main moved, try again in this lock
    REST = "rest"  # a network error: rest first


@dataclass
class Land:
    """What survives from one try of the land to the next."""

    pushes: int = 0  # rejected pushes so far
    flaky: int = 0  # network errors on the push while the network looked up
    phase: Phase = Phase.FRESH
    moved: int = 0  # times the lock was let go because main moved under the gate: the gate runs outside again (land_optimistic_tries)
