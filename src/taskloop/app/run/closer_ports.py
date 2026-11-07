"""Bind the stage capabilities used by one closing run."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from tlkernel.identity import Identity
from tlpipeline.closing import CloseParts, Closer
from tlpipeline.closing_branch import ReleaseSlot, SaveBranch
from tlpipeline.closing_decide import Decide
from tlpipeline.closing_host import CloseAllCheckpoints, CloserHost
from tlpipeline.closing_notes import FileNotes, Reflect
from tlpipeline.closing_record import RecordRun
from tlpipeline.closing_settle import Settle
from tlpipeline.ports import AskRules, BeadClosing, FollowUps, LandCleanup, ParkBook

from taskloop.adapters import beadtools, closes
from taskloop.app.asks.closing import ClosingAsks
from taskloop.app.land.closing import LandCleanups, LandFollowUps
from taskloop.app.land.followups import FollowUpCheckpoints, FollowUpHost, file_follow_ups
from taskloop.app.slots.config import profile_slots
from taskloop.app.track.closing import ClosingBeads
from taskloop.app.wire import closeguard
from taskloop.app.wire.slots import slot_of
from taskloop.stores.runlog import RunLog


class BindingCheckpoints(CloseAllCheckpoints, FollowUpCheckpoints, Protocol):
    pass


class BindingHost(CloserHost, FollowUpHost, Protocol):
    @property
    def log(self) -> RunLog: ...
    @property
    def who(self) -> Identity: ...
    @property
    def checkpoints(self) -> BindingCheckpoints: ...


@dataclass(frozen=True)
class ClosingPorts:
    asks: ParkBook
    rules: AskRules
    cleanup: LandCleanup
    beads: BeadClosing
    follow_ups: FollowUps


def closing_ports(e: BindingHost) -> ClosingPorts:
    asks = ClosingAsks(e.home)
    cleanup = LandCleanups(e.git, e.log, e.home,
                           slot_check=lambda repo: (lambda path: bool(slot_of(repo, path, e.who, e.store, strict=True))),
                           base_of=lambda repo: profile_slots(repo).base)
    return ClosingPorts(asks, asks, cleanup, ClosingBeads(e.who, e.store, closeguard.ENGINE),
                        LandFollowUps(lambda: file_follow_ups(e)))

def closer_over(host: BindingHost, after_save: Callable[[], None] | None = None) -> Closer:
    """The Closer over the engine: each step gets the host typed as that step's own Protocol."""
    ports = closing_ports(host)
    return Closer(host, CloseParts(
        decide=Decide(host, closes.recent_closes), branch=SaveBranch(host, after_save),
        slot=ReleaseSlot(host, host.tree, ports.cleanup), record=RecordRun(host),
        notes=FileNotes(host, ports.follow_ups, beadtools.attempt), reflect=Reflect(host),
        settle=Settle(host, ports.beads, ports.asks, beadtools.peek, beadtools.attempt)), ports.rules, ports.asks, beadtools.peek)
