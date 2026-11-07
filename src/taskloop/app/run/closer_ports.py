"""Bind the stage capabilities used by one closing run."""
from dataclasses import dataclass

from taskloop.app.asks.closing import ClosingAsks
from taskloop.app.land.closing import LandFollowUps
from taskloop.app.land.followups import file_follow_ups
from taskloop.app.pipeline.ports import BeadClosing, FollowUps, ParkBook
from taskloop.app.run import console
from taskloop.app.run.closer_host import CloserHost
from taskloop.app.track.closing import ClosingBeads
from taskloop.app.wire import closeguard
from taskloop.contracts.stagefacts import Narrate


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
    beads: BeadClosing
    follow_ups: FollowUps
    say: Narrate


def closing_ports(e: CloserHost) -> ClosingPorts:
    return ClosingPorts(ClosingAsks(e.home), ClosingBeads(e.who, e.store, closeguard.ENGINE),
                        LandFollowUps(lambda: file_follow_ups(e)), ConsoleNarrate())
