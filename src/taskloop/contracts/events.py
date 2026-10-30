"""Event: the union of records appended to events.jsonl, the cross-repo index of claims, stages, slots and landings (v2)."""
from typing import ClassVar, final

from taskloop.contracts.enums import WhyCode
from taskloop.contracts.wire import Tagged, load


class EventRec(Tagged):
    V: ClassVar[int] = 2
    t: float
    bead: str
    session: str = ""
    actor: str = ""
    repo: str = ""
    host: str = ""


@final
class Claim(EventRec, tag="claim"):
    branch: str = ""
    slot: str | None = None
    title: str = ""
    worktree: str = ""


@final
class Stage(EventRec, tag="stage"):
    step: str = ""
    text: str = ""


@final
class SlotTake(EventRec, tag="slot_take"):
    slot: str = ""
    slot_bead: str = ""
    ticket: int | None = None
    worktree: str = ""


@final
class SlotRelease(EventRec, tag="slot_release"):
    slot: str = ""


@final
class SlotSetup(EventRec, tag="slot_setup"):
    exit: int = 0
    secs: float = 0.0


@final
class SlotHold(EventRec, tag="slot_hold"):
    until: float | None = None
    why: str = ""


@final
class SlotAside(EventRec, tag="slot_aside"):
    held: str = ""
    why: str = ""


@final
class Block(EventRec, tag="block"):
    why_code: WhyCode | None = None
    why: str = ""


@final
class BeadClosed(EventRec, tag="close"):
    reason: str = ""


@final
class Land(EventRec, tag="land"):
    sha: str = ""


@final
class CodeReloaded(EventRec, tag="reload"):
    code_dir: str = ""
    new: str = ""
    old: str = ""
    who: str = ""
    why: str = ""


@final
class WorktreeStart(EventRec, tag="worktree_start"):
    worktree: str = ""


Event = (
    Claim | Stage | SlotTake | SlotRelease | SlotSetup | SlotHold | SlotAside | Block | BeadClosed | Land | CodeReloaded | WorktreeStart
)


def decode(data: object) -> Event:
    """The event record `data` is; msgspec.ValidationError (StaleRecord for a foreign v) otherwise."""
    return load(Event, data)
