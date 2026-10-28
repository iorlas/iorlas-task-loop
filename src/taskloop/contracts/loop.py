"""Loop records: one state file per loop, the commands sent to it, and its rests."""
from dataclasses import field
from typing import ClassVar, Literal

from taskloop.contracts.codec import record


@record
class StopRequest:
    kind: Literal["now", "after_current"]
    by: str = ""
    t: float = 0.0


SkipKind = Literal["epic", "slot", "label", "epic_only", "lint", "area", "rest", "lane", "taken", "hold"]


@record
class Skip:
    """Why a ready bead is not taken now. `kind` is the rule that skipped it, never parsed back out of `why`."""

    why: str
    until: float | None = None
    kind: SkipKind = "label"
    area: str = ""  # kind "area": the busy area, the bead that runs in it and where
    holder: str = ""
    where: str = ""


@record
class QueueRow:
    bead: str
    prio: int
    since: float
    ahead: int = 0
    skip: Skip | None = None
    reason: str = ""  # the rule that puts the bead before the next one ("priority P1 before P2")
    title: str = ""


@record
class Carry:
    """What a loop hands to the install it moves to (the state JSON in TL_LOOP_STATE): counters and rests of this loop run."""

    fails: list[str] = field(default_factory=list)
    ran: int = 0
    later: dict[str, float] = field(default_factory=dict)
    pauses: dict[str, int] = field(default_factory=dict)
    gated: dict[str, tuple[str, float]] = field(default_factory=dict)
    warned: list[str] = field(default_factory=list)
    until: float = 0.0
    wt: str = ""
    back: str = ""  # the install dir this loop moved from, and when: a crash soon after the move goes back to it once
    moved_at: float = 0.0
    fallback: bool = False


@record
class LoopState:
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
    queue: list[QueueRow] = field(default_factory=list)
    lanes_seen: list[str] = field(default_factory=list)
    log: str = ""
    carry: Carry = field(default_factory=Carry)


@record
class LoopCommand:
    """loop/<repo_key>.command.json: `tl stop` writes it. The loops it names (the repo's live loops when it was written) obey
    it; a loop started later ignores it; the last named loop to end deletes it."""

    V: ClassVar[int] = 1
    action: Literal["stop_now", "stop_after_current", "resume"]
    by: str
    t: float
    targets: list[int] = field(default_factory=list)


@record
class Rest:
    """loop/<key>-rest.json: {bead: when it may be taken again} for the beads that failed before their engine started or
    cooled after a fault; shared by every loop on the repo."""

    V: ClassVar[int] = 2
    beads: dict[str, float] = field(default_factory=dict)


@record
class BadVersion:
    """An install that failed its selftest or crashed a run. It holds while the install's `key` is the one recorded."""

    version: str
    why: str
    t: float
    seen_by: str = ""
    key: str = ""


@record
class BadVersions:
    """bad-versions.json."""

    V: ClassVar[int] = 1
    entries: list[BadVersion] = field(default_factory=list)
