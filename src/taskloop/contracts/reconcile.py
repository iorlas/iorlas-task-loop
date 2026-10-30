"""The lease and loop facts a reconcile sweep observes, and the two rules over them (strays, an absent loop). Pure: no bd, no clock,
no process. They live here, not in domain/, because the dashboard reads the same facts through the same rules and imports contracts only."""
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from taskloop.contracts.ids import BeadId

LOOP_ABSENT_S: Final = 600  # ready beads, no live loop and no beat for this long: the loop is absent (NoLoop)
LOOP_STALL_S: Final = 1800  # a loop beats, ready beads wait and the repo logged no event for this long: the loop is stalled
ACTOR_PREFIX: Final = "tl-"  # an engine's or a loop's actor; any other holder is a person's hand claim and never swept


@dataclass(frozen=True)
class Lease:
    """A bead held in progress: who holds it, at which FENCE generation (the bead's `fence_gen`), when bd's lease ends (epoch seconds,
    0 when none), and `live`: a run of it is running now."""
    bead: BeadId
    holder: str
    gen: int
    expires: float = 0.0
    live: bool = False


@dataclass(frozen=True)
class SlotFact:
    """A slot bead: `bead` its id, `name` the slot, `claimed` it is in progress, `holder` its assignee, `gen` its `held_gen`,
    `expires` bd's lease end (0 none), `hold_until` a person's hold (0 none), `live`: a run is on the slot now, `held`: the bead
    its holder marked it for (`held_bead`), "" when none."""
    bead: BeadId
    name: str
    claimed: bool
    holder: str = ""
    gen: int = 0
    expires: float = 0.0
    hold_until: float = 0.0
    live: bool = False
    held: str = ""


@dataclass(frozen=True)
class LoopFact:
    """A live loop of the repo (from its state file): pid, `started` (which tells a loop from a later one on a recycled pid) and
    the time of its last beat."""
    pid: int
    started: float
    beat: float


@dataclass(frozen=True)
class Stray:
    """A claim nothing runs under. `kind`: "bead" or "slot"; `ref`: the bead id (the slot bead's id for a slot); `gen`: the
    generation seen, which an action must still find; `expired`: it may be given back (bd's lease on it ended, a bead's claim has
    no lease, or its holder went on to another bead)."""
    kind: str
    ref: BeadId
    name: str
    holder: str
    gen: int
    expired: bool

    @property
    def why(self) -> str:
        return f"claimed by {self.holder or '?'}, no live run" + (" (lease ended)" if self.expired else "")


def epoch(stamp: str) -> float:
    """bd's lease end as epoch seconds, 0 when there is none or it does not read."""
    try:
        return datetime.fromisoformat(stamp).timestamp() if stamp else 0.0
    except ValueError:
        return 0.0


def ended(expires: float, now: float) -> bool:
    return bool(expires) and expires < now


def strays(leases: tuple[Lease, ...], slots: tuple[SlotFact, ...], now: float) -> list[Stray]:
    """Every claimed bead of an engine actor and every claimed slot (not held by a person) with no live run. A lease still running
    is shown, not swept: only `expired` ones are for an action. A bead's claim is also given back when it has no lease at all, or
    when its holder keeps a slot inside its lease that is marked for another bead (the holder went on and left this claim)."""
    marked: dict[str, set[str]] = {}
    for s in slots:
        if s.claimed and s.held and not ended(s.expires, now):
            marked.setdefault(s.holder, set()).add(s.held)
    found = [Stray("bead", x.bead, x.bead, x.holder, x.gen,
                   not x.expires or ended(x.expires, now) or bool(marked.get(x.holder, set()) - {x.bead}))
             for x in leases if x.holder.startswith(ACTOR_PREFIX) and not x.live]
    found += [Stray("slot", s.bead, s.name, s.holder, s.gen, ended(s.expires, now))
              for s in slots if s.claimed and s.hold_until <= now and not s.live]
    return found


def loop_absent(loops: tuple[LoopFact, ...], ready: int, last_beat: float, now: float, absent: float) -> bool:
    """Ready beads, no live loop and no beat for `absent` seconds."""
    return not loops and ready > 0 and (not last_beat or now - last_beat > absent)
