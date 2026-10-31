"""The run storm detector: the same FAULT fingerprint on STORM_BEADS distinct beads inside the window trips it. Pure.

It stamps run fingerprints and never marks a lane (the delegate owns the lane breaker). One `storm` record is written (once, by
adapters/storm.py) and one banner is printed; the beads stay open and no per-bead ask is raised.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

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
    cut = now - knobs["storm_window_s"]
    beads = {bead}
    for h in history:
        if h.get("fingerprint") != fingerprint or float(h.get("t") or 0) < cut:
            continue
        try:
            if oc.POLICY[Kind(h.get("kind"))].storm:
                beads.add(str(h.get("bead")))
        except ValueError:
            continue
    if len(beads) < knobs["storm_beads"]:
        return None
    return StormTrip(fingerprint, tuple(sorted(beads)), now)


def banner(trip: StormTrip, record: str) -> str:
    """The stop line: the beads stay open; the way to start sooner is to delete the record at `record`."""
    return "STOPPED: storm {} on {} (the beads stay open; look at their logs, then delete {})".format(
        trip.fingerprint, ",".join(trip.beads), record)
