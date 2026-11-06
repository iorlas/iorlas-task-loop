"""The run storm detector: the same FAULT fingerprint on STORM_BEADS distinct beads inside the window trips it. Pure.

It stamps run fingerprints and never marks a lane (the delegate owns the lane breaker). One `storm` record is written (once, by
adapters/storm.py) and one banner is printed; the beads stay open and no per-bead ask is raised.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from any_failure_fp import Event, trip

from taskloop.contracts.kinds import Kind
from taskloop.domain import outcome as oc


@dataclass(frozen=True)
class StormTrip:
    fingerprint: str
    beads: tuple[str, ...]
    t: float


def storm_trip(history: Sequence[Mapping[str, Any]], bead: str, kind: Kind, fingerprint: str, now: float,
               knobs: Mapping[str, float] = oc.KNOBS) -> StormTrip | None:
    """The trip this close causes, or None. history: earlier closes {bead, kind, fingerprint, t}; (bead, kind, fingerprint)
    is the close being made. Only FAULT_* count: an ask repeats legitimately, a lane or network pause is gated by its wake."""
    if not oc.POLICY[kind].storm:
        return None
    events = [Event(str(h.get("bead")), str(h.get("fingerprint")), float(h.get("t") or 0), str(h.get("kind"))) for h in history]
    found = trip(events, bead, fingerprint, now, window_s=knobs["storm_window_s"], min_keys=int(knobs["storm_beads"]), count=_storms)
    return StormTrip(found.fp, found.keys, found.t) if found else None


def _storms(e: Event) -> bool:
    try:
        return oc.POLICY[Kind(e.kind)].storm
    except ValueError:
        return False


def banner(trip: StormTrip, record: str) -> str:
    """The stop line: the beads stay open; the way to start sooner is to delete the record at `record`."""
    return "WAIT: storm {} on {} (the beads stay open; the record expires, or clear {} to wake sooner)".format(
        trip.fingerprint, ",".join(trip.beads), record)
