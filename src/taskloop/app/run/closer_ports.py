"""Bind the stage capabilities used by one closing run."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from tlasks.closing import ClosingAsks
from tlkernel.identity import Identity
from tlpipeline import api
from tlslots.config import profile_slots

from taskloop.adapters import beadtools, closes
from taskloop.app.land.closing import LandCleanups, LandFollowUps
from taskloop.app.land.record import FollowUpCheckpoints, FollowUpHost, file_follow_ups
from taskloop.app.track import closeguard
from taskloop.app.track.closing import ClosingBeads
from taskloop.app.wire import slotfx
from taskloop.app.wire.slots import slot_of
from taskloop.stores.runlog import RunLog


class BindingCheckpoints(api.CloseCheckpoints, api.BranchCheckpoints, api.NotesCheckpoints, api.ReflectCheckpoints,
                         FollowUpCheckpoints, Protocol):
    pass


class BindingTree(api.BranchTree, api.Slotting, Protocol):
    pass


class BindingHost(api.CloseState, api.CloseRuntime, api.CloseStats, api.DecideHost, api.SaveBranchHost, api.ReleaseSlotHost,
                  api.RecordHost, api.FileNotesHost, api.ReflectHost, api.SettleHost, FollowUpHost, Protocol):
    @property
    def tree(self) -> BindingTree: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def who(self) -> Identity: ...
    @property
    def checkpoints(self) -> BindingCheckpoints: ...


@dataclass(frozen=True)
class ClosingPorts:
    asks: api.ParkBook
    rules: api.AskRules
    cleanup: api.LandCleanup
    beads: api.BeadClosing
    follow_ups: api.FollowUps


def closing_ports(e: BindingHost) -> ClosingPorts:
    asks = ClosingAsks(e.home)
    cleanup = LandCleanups(e.git, e.log, e.home,
                           slot_check=lambda repo: (lambda path: bool(slot_of(repo, path, e.who, e.store, strict=True))),
                           base_of=lambda repo: profile_slots(repo).base, history=e.log.log, fx=slotfx.FX)
    return ClosingPorts(asks, asks, cleanup, ClosingBeads(e.who, e.store, closeguard.ENGINE),
                        LandFollowUps(lambda: file_follow_ups(e)))

def closer_over(host: BindingHost, after_save: Callable[[], None] | None = None) -> api.Closer:
    """The Closer over the engine: each step gets the host typed as that step's own Protocol."""
    ports = closing_ports(host)
    return api.Closer(host, host, host, api.CloseParts(
        decide=api.Decide(host, closes.recent_closes), branch=api.SaveBranch(host, after_save),
        slot=api.ReleaseSlot(host, host.tree, ports.cleanup), record=api.RecordRun(host),
        notes=api.FileNotes(host, ports.follow_ups, beadtools.attempt), reflect=api.Reflect(host),
        settle=api.Settle(host, ports.beads, ports.asks, beadtools.peek, beadtools.attempt)), ports.rules, ports.asks, beadtools.peek)
