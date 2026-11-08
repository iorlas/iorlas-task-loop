"""Refresh, check, claim and publish occupancy under one area lock."""
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Literal, Protocol

from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure
from tlkernel.ids import BeadId
from tlkernel.loop import Skip

from tlareas.host import AreasHost
from tlareas.policy import Areas, area_busy_text, has_areas


class AreaRule(Protocol):
    running: dict[BeadId, str]

    def area_busy(self, bead: Bead, /) -> tuple[str, Skip | None]: ...


@dataclass(frozen=True)
class Admission:
    kind: Literal["busy", "not_won", "won"]
    why: str


def hand(host: AreasHost, bead_id: BeadId, exclusive: bool, take_engine: Callable[[], str],
         mark: Callable[[], None]) -> str:
    """Take a hand run's engine lock, warning or refusing when its area is occupied."""
    with host.area_lock() if has_areas(host) else nullcontext():
        if has_areas(host):
            try:
                bead = host.store.show(bead_id)
            except BdFailure:
                bead = None
            bead = bead or Bead(id=bead_id, title="", status="")
            areas = Areas(host.store, host.areas, host.area_label_prefix, host.running(), host.say)
            _area, busy = area_busy_text(areas, bead)
            if busy and exclusive:
                return busy + " (--exclusive-area)"
            if busy:
                host.say(f"⚠ {busy}: running anyway beside it; --exclusive-area refuses instead")
        why = take_engine()
        if not why:
            mark()
        return why


def loop(host: AreasHost, bead: Bead, rule: AreaRule, claim: Callable[[], tuple[bool, str]],
         publish: Callable[[], None]) -> Admission:
    """Admit a loop candidate; publish only a won claim with a configured area."""
    with host.area_lock() if has_areas(host) else nullcontext():
        area = ""
        if has_areas(host):
            rule.running = host.running()  # refresh after the slot wait, inside the lock (tl-na3)
            area, busy = rule.area_busy(bead)
            if busy:
                return Admission("busy", busy.why)
        won, why = claim()
        if not won:
            return Admission("not_won", why)
        if area:
            publish()
        return Admission("won", "")
