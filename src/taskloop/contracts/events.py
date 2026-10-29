"""Event: the union of records appended to events.jsonl, the cross-repo index of claims, stages, slots and landings (v2)."""
from typing import Annotated, ClassVar, Literal

from pydantic import Field

from taskloop.contracts.enums import WhyCode
from taskloop.contracts.wire import Rec, load


class EventRec(Rec):
    V: ClassVar[int] = 2
    kind: str = ""  # each member narrows it to its tag; declared here so `kind` is written right after `v`
    t: float
    bead: str
    session: str = ""
    actor: str = ""
    repo: str = ""
    host: str = ""


class Claim(EventRec):
    kind: Literal["claim"] = "claim"
    branch: str = ""
    slot: str | None = None
    title: str = ""
    worktree: str = ""


class Stage(EventRec):
    kind: Literal["stage"] = "stage"
    step: str = ""
    text: str = ""


class SlotTake(EventRec):
    kind: Literal["slot_take"] = "slot_take"
    slot: str = ""
    slot_bead: str = ""
    ticket: int | None = None
    worktree: str = ""


class SlotRelease(EventRec):
    kind: Literal["slot_release"] = "slot_release"
    slot: str = ""


class SlotSetup(EventRec):
    kind: Literal["slot_setup"] = "slot_setup"
    exit: int = 0
    secs: float = 0.0


class SlotHold(EventRec):
    kind: Literal["slot_hold"] = "slot_hold"
    until: float | None = None
    why: str = ""


class SlotAside(EventRec):
    kind: Literal["slot_aside"] = "slot_aside"
    held: str = ""
    why: str = ""


class Block(EventRec):
    kind: Literal["block"] = "block"
    why_code: WhyCode | None = None
    why: str = ""


class BeadClosed(EventRec):
    kind: Literal["close"] = "close"
    reason: str = ""


class Land(EventRec):
    kind: Literal["land"] = "land"
    sha: str = ""


class CodeReloaded(EventRec):
    kind: Literal["reload"] = "reload"
    code_dir: str = ""
    new: str = ""
    old: str = ""
    who: str = ""
    why: str = ""


class WorktreeStart(EventRec):
    kind: Literal["worktree_start"] = "worktree_start"
    worktree: str = ""


Event = Annotated[
    Claim | Stage | SlotTake | SlotRelease | SlotSetup | SlotHold | SlotAside | Block | BeadClosed | Land | CodeReloaded | WorktreeStart,
    Field(discriminator="kind"),
]


def decode(data: object) -> Event:
    """The event record `data` is; ValidationError (StaleRecord for a foreign v) otherwise."""
    return load(Event, data)
