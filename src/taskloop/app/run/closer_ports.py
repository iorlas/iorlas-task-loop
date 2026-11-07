"""Bind the stage capabilities used by one closing run."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from taskloop.app.asks.closing import ClosingAsks
from taskloop.app.land.closing import LandCleanups, LandFollowUps
from taskloop.app.land.followups import FollowUpCheckpoints, FollowUpHost, file_follow_ups
from taskloop.app.pipeline.closing import CloseParts, Closer
from taskloop.app.pipeline.closing_branch import ReleaseSlot, SaveBranch
from taskloop.app.pipeline.closing_decide import Decide
from taskloop.app.pipeline.closing_host import CloseAllCheckpoints, CloserHost
from taskloop.app.pipeline.closing_notes import FileNotes, Reflect
from taskloop.app.pipeline.closing_record import RecordRun
from taskloop.app.pipeline.closing_settle import Settle
from taskloop.app.pipeline.ports import AskRules, BeadClosing, FollowUps, LandCleanup, ParkBook
from taskloop.app.run import console
from taskloop.app.track.closing import ClosingBeads
from taskloop.app.wire import closeguard
from taskloop.app.wire.slots import profile_slots, slot_of
from taskloop.contracts.identity import Identity
from taskloop.contracts.stagefacts import Narrate


class BindingCheckpoints(CloseAllCheckpoints, FollowUpCheckpoints, Protocol):
    pass


class BindingHost(CloserHost, FollowUpHost, Protocol):
    @property
    def who(self) -> Identity: ...
    @property
    def checkpoints(self) -> BindingCheckpoints: ...


class ConsoleNarrate:
    def note(self, text: str) -> int:
        console.say(text)
        return 0

    def warn(self, text: str) -> int:
        console.say(text)
        return 0


@dataclass(frozen=True)
class ClosingPorts:
    asks: ParkBook
    rules: AskRules
    cleanup: LandCleanup
    beads: BeadClosing
    follow_ups: FollowUps
    say: Narrate


def closing_ports(e: BindingHost) -> ClosingPorts:
    asks = ClosingAsks(e.home)
    cleanup = LandCleanups(e.git, e.log, e.home,
                           slot_check=lambda repo: (lambda path: bool(slot_of(repo, path, e.who, e.store, strict=True))),
                           base_of=lambda repo: profile_slots(repo).base)
    return ClosingPorts(asks, asks, cleanup, ClosingBeads(e.who, e.store, closeguard.ENGINE),
                        LandFollowUps(lambda: file_follow_ups(e)), ConsoleNarrate())

def closer_over(host: BindingHost, after_save: Callable[[], None] | None = None) -> Closer:
    """The Closer over the engine: each step gets the host typed as that step's own Protocol."""
    ports = closing_ports(host)
    return Closer(host, CloseParts(
        decide=Decide(host, ports.say), branch=SaveBranch(host, after_save),
        slot=ReleaseSlot(host, host.tree, ports.cleanup), record=RecordRun(host),
        notes=FileNotes(host, ports.follow_ups), reflect=Reflect(host),
        settle=Settle(host, ports.beads, ports.asks)), ports.rules, ports.asks)
