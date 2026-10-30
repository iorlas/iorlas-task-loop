"""Loop records: one state file per loop, the commands sent to it, and its rests."""
from typing import ClassVar, Literal

import msgspec

from taskloop.contracts.wire import Rec


class StopRequest(Rec):
    kind: Literal["now", "after_current"]
    by: str = ""
    t: float = 0.0


SkipKind = Literal["epic", "slot", "label", "epic_only", "lint", "area", "rest", "lane", "taken", "hold"]


class Skip(Rec):
    """Why a ready bead is not taken now. `kind` is the rule that skipped it, never parsed back out of `why`."""

    why: str
    until: float | None = None
    kind: SkipKind = "label"
    area: str = ""  # kind "area": the busy area, the bead that runs in it and where
    holder: str = ""
    where: str = ""


class QueueRow(Rec):
    bead: str
    prio: int
    since: float
    ahead: int = 0
    skip: Skip | None = None
    reason: str = ""  # the rule that puts the bead before the next one ("priority P1 before P2")
    title: str = ""


class Carry(Rec):
    """What a loop hands to the install it moves to (the state JSON in TL_LOOP_STATE): counters and rests of this loop run."""

    fails: list[str] = msgspec.field(default_factory=list)
    ran: int = 0
    later: dict[str, float] = msgspec.field(default_factory=dict)
    pauses: dict[str, int] = msgspec.field(default_factory=dict)
    gated: dict[str, tuple[str, float]] = msgspec.field(default_factory=dict)
    warned: list[str] = msgspec.field(default_factory=list)
    until: float = 0.0
    wt: str = ""
    back: str = ""  # the install dir this loop moved from, and when: a crash soon after the move goes back to it once
    moved_at: float = 0.0
    fallback: bool = False


class LoopState(Rec):
    """loop/<repo_key>.<pid>.json, rewritten by the loop every pass; the dashboard and `tl status` read it."""

    V: ClassVar[int] = 2
    pid: int
    started: float
    t: float
    repo: str
    version: str
    code_dir: str
    actor: str
    pid_start: float | None = None
    bead: str | None = None
    slot: str | None = None
    since: float | None = None
    child: int | None = None
    run_log: str = ""
    worktree: str = ""
    stop: StopRequest | None = None
    queue: list[QueueRow] = msgspec.field(default_factory=list)
    lanes_seen: list[str] = msgspec.field(default_factory=list)
    log: str = ""
    carry: Carry = msgspec.field(default_factory=Carry)


class LoopTarget(Rec):
    """One loop a command names: its pid and `started` (kept across the loop's own re-exec), so a loop started later on a recycled
    pid is not the one meant."""

    pid: int
    started: float


class LoopCommand(Rec):
    """loop/<repo_key>.command.json: `tl stop` writes it. The loops it names (the repo's live loops when it was written) obey
    it; a loop started later, or on a recycled pid, ignores it; the last named loop to end deletes it."""

    V: ClassVar[int] = 2
    action: Literal["stop_now", "stop_after_current", "resume"]
    by: str
    t: float
    targets: list[LoopTarget] = msgspec.field(default_factory=list)


class Rest(Rec):
    """loop/<key>-rest.json: {bead: when it may be taken again} for the beads that failed before their engine started or
    cooled after a fault; shared by every loop on the repo."""

    V: ClassVar[int] = 2
    beads: dict[str, float] = msgspec.field(default_factory=dict)


class BadVersion(Rec):
    """An install that failed its selftest or crashed a run. It holds while the install's `key` is the one recorded."""

    version: str
    why: str
    t: float
    seen_by: str = ""
    key: str = ""


class BadVersions(Rec):
    """bad-versions.json."""

    V: ClassVar[int] = 1
    entries: list[BadVersion] = msgspec.field(default_factory=list)
