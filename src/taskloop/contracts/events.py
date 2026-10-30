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
    slot_bead: str = ""


@final
class SlotSetup(EventRec, tag="slot_setup"):
    slot: str = ""
    worktree: str = ""
    exit: int = 0
    secs: float = 0.0


@final
class SlotHold(EventRec, tag="slot_hold"):
    slot: str = ""
    slot_bead: str = ""
    until: float | None = None
    why: str = ""


@final
class SlotAside(EventRec, tag="slot_aside"):
    slot: str = ""
    held: bool = False  # the hold was taken (False: another loop has the slot)
    why: str = ""


@final
class SlotHoldExpired(EventRec, tag="slot_hold_expired"):
    slot: str = ""
    slot_bead: str = ""


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
    step: str = ""
    run: str = ""


@final
class ReloadFallback(EventRec, tag="reload_fallback"):
    who: str = ""
    old: str = ""
    new: str = ""
    why: str = ""
    run: str = ""


@final
class WorktreeStart(EventRec, tag="worktree_start"):
    worktree: str = ""


@final
class WorktreeSunset(EventRec, tag="worktree_sunset"):
    worktree: str = ""


@final
class LoopExit(EventRec, tag="loop_exit"):
    who: str = ""
    pid: int = 0
    reason: str = ""
    detail: str = ""


@final
class NetUp(EventRec, tag="net_up"):
    who: str = ""
    down_s: float = 0.0


@final
class NetDown(EventRec, tag="net_down"):
    who: str = ""
    why: str = ""


@final
class InstallMissing(EventRec, tag="install_missing"):
    who: str = ""
    version: str = ""
    running: str = ""
    target: str = ""


Event = (
    Claim | Stage | SlotTake | SlotRelease | SlotSetup | SlotHold | SlotAside | SlotHoldExpired | Block | BeadClosed | Land | CodeReloaded
    | ReloadFallback | WorktreeStart | WorktreeSunset | LoopExit | NetUp | NetDown | InstallMissing
)


def decode(data: object) -> Event:
    """The event record `data` is; msgspec.ValidationError (StaleRecord for a foreign v) otherwise."""
    return load(Event, data)
