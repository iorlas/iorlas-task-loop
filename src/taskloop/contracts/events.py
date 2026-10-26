"""Event: the union of records appended to events.jsonl, the cross-repo index of claims, stages, slots and landings (v2)."""
from typing import ClassVar

from taskloop.contracts.codec import from_tagged, record, table_of
from taskloop.contracts.enums import WhyCode


@record
class EventRec:
    V: ClassVar[int] = 2
    t: float
    bead: str
    session: str = ""
    actor: str = ""
    repo: str = ""
    host: str = ""


@record
class Claim(EventRec):
    KIND: ClassVar[str] = "claim"
    branch: str = ""
    slot: str | None = None
    title: str = ""
    worktree: str = ""


@record
class Stage(EventRec):
    KIND: ClassVar[str] = "stage"
    step: str = ""
    text: str = ""


@record
class SlotTake(EventRec):
    KIND: ClassVar[str] = "slot_take"
    slot: str = ""
    slot_bead: str = ""
    ticket: int | None = None
    worktree: str = ""


@record
class SlotRelease(EventRec):
    KIND: ClassVar[str] = "slot_release"
    slot: str = ""


@record
class SlotSetup(EventRec):
    KIND: ClassVar[str] = "slot_setup"
    exit: int = 0
    secs: float = 0.0


@record
class SlotHold(EventRec):
    KIND: ClassVar[str] = "slot_hold"
    until: float | None = None
    why: str = ""


@record
class SlotAside(EventRec):
    KIND: ClassVar[str] = "slot_aside"
    held: str = ""
    why: str = ""


@record
class Block(EventRec):
    KIND: ClassVar[str] = "block"
    why_code: WhyCode | None = None
    why: str = ""


@record
class BeadClosed(EventRec):
    KIND: ClassVar[str] = "close"
    reason: str = ""


@record
class Land(EventRec):
    KIND: ClassVar[str] = "land"
    sha: str = ""


@record
class CodeReloaded(EventRec):
    KIND: ClassVar[str] = "reload"
    code_dir: str = ""
    new: str = ""
    old: str = ""
    who: str = ""


@record
class WorktreeStart(EventRec):
    KIND: ClassVar[str] = "worktree_start"
    worktree: str = ""


Event = (Claim | Stage | SlotTake | SlotRelease | SlotSetup | SlotHold | SlotAside | Block | BeadClosed | Land | CodeReloaded
         | WorktreeStart)
EVENT = table_of(Claim, Stage, SlotTake, SlotRelease, SlotSetup, SlotHold, SlotAside, Block, BeadClosed, Land, CodeReloaded,
                 WorktreeStart)


def decode(data: object) -> Event:
    """The event record `data` is; CodecError (StaleRecord for a foreign v) otherwise."""
    return from_tagged(EVENT, data)
