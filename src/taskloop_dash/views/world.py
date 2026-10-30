"""What the v2 builders are given: the engine's and bd's facts of one moment, typed and already read (taskloop_dash.readers.world makes
it; a test builds it from recorded logs and fakes). Nothing in it is a path or a process."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from taskloop.contracts.ask import Ask
from taskloop.contracts.bead import Bead
from taskloop.contracts.ledger import Adr, LedgerEntry
from taskloop.contracts.loop import LoopState
from taskloop.contracts.reconcile import Stray
from taskloop.contracts.snapshots import StatusSnapshot
from taskloop_dash.views.runfacts import Run


@dataclass(frozen=True)
class LookItem:
    """One open item of an owner-look bead: the bead it is about and the pictures to look at (urls the page can load)."""

    bead: str
    title: str
    shots: tuple[str, ...]


@dataclass(frozen=True)
class AdrIn:
    """A decision in force and how often plans cited it."""

    adr: Adr
    reuses: int = 0
    last_used: float | None = None


@dataclass(frozen=True)
class Landing:
    """A run of the retained traces that landed: when it ended and how many times its plan was redone."""

    t: float
    replans: int = 0


@dataclass(frozen=True)
class ProjectIn:
    id: str
    name: str
    beads: Sequence[Bead]  # bd list, closed ones too, slot and look beads included
    slots: Sequence[Bead] = ()  # this machine's slot beads
    loops: Sequence[LoopState] = ()  # every loop state file of the repo
    looks: Sequence[LookItem] = ()
    adrs: Sequence[AdrIn] = ()  # the repo's decisions in force, oldest first
    strays: Sequence[Stray] = ()  # claims nothing runs under (readers/observed.py: the reconcile sweep's rule)


@dataclass(frozen=True)
class World:
    now: float
    host: str
    version: str  # the server's code version
    projects: Sequence[ProjectIn]
    runs: Mapping[str, Sequence[Run]]  # bead id -> its runs in the retained logs, oldest first
    asks: Mapping[str, Ask]  # bead id -> its open or parked ask
    status: StatusSnapshot | None = None  # delegate's status as `tl lanes` last filed it
    ledger: Sequence[LedgerEntry] = ()  # the ask ledger, oldest row first
    landings: Sequence[Landing] = ()  # runs that landed, from the traces (the learning series' denominator)
    skipped_traces: int = 0  # trace lines that are not a RunTrace of this version: left out, never guessed at
