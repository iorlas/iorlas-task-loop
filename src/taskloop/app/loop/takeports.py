"""What the loop's take reads of the stages around it (slots, asks): two small ports, and the adapters over the real stages. take.py names
the ports and imports no stage; this file is where the loop meets them."""
from typing import Protocol

from taskloop.app.asks import parks
from taskloop.app.loop.env import LoopEnv
from taskloop.app.slots.pool import SlotPool
from taskloop.app.slots.reset import setup
from taskloop.contracts.bead import Bead
from taskloop.contracts.beadsport import BdFailure
from taskloop.contracts.ids import BeadId
from taskloop.contracts.slots import SlotFail, SlotGitError


class TakeSlots(Protocol):
    def ready_for(self, slot: str, bead: str) -> None:
        """A clean tree on the bead's branch in the slot, leftover work committed. SlotFail (code, why, setup) when it cannot."""

    def sets_up_at_base(self, slot: str) -> bool:
        """Whether the slot, detached at the base, passes its setup."""


class TakeParks(Protocol):
    def held(self, b: Bead) -> bool:
        """The bead is parked, held or waiting for an answer: not to be taken now."""


class LeaseView(Protocol):
    def add(self, bead_id: BeadId) -> None: ...
    def drop(self, bead_id: BeadId) -> None: ...


class EngineSlots:
    def __init__(self, env: LoopEnv) -> None:
        self.env = env

    def ready_for(self, slot: str, bead: str) -> None:
        SlotPool(self.env.slot_env()).named(slot).ready_for(bead)

    def sets_up_at_base(self, slot: str) -> bool:
        try:
            target = SlotPool(self.env.slot_env()).named(slot)
            target.ready_for("")
            setup(target, force=True)
        except (SlotFail, SlotGitError, BdFailure, OSError):
            return False
        return True


class ParkGate:
    def __init__(self, env: LoopEnv) -> None:
        self.env = env

    def held(self, b: Bead) -> bool:
        return parks.gate(self.env.cfgdir, b, now=self.env.now()) is not None
