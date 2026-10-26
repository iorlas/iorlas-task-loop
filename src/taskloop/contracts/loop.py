"""Loop records: one state file per loop, the commands sent to it, and its rests."""
from dataclasses import field
from typing import ClassVar, Literal

from taskloop.contracts.codec import record


@record
class StopRequest:
    kind: Literal["now", "after_current"]
    by: str = ""
    t: float = 0.0


@record
class Skip:
    why: str
    until: float | None = None


@record
class QueueRow:
    bead: str
    prio: int
    since: float
    ahead: int = 0
    skip: Skip | None = None


@record
class LoopState:
    """loop/<repo_key>.json, rewritten by the loop every pass; the dashboard and `tl status` read it."""

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


@record
class LoopCommand:
    """loop/<repo_key>.command.json: the dashboard and `tl stop` write it, the loop consumes and deletes it."""

    V: ClassVar[int] = 1
    action: Literal["stop_now", "stop_after_current", "resume"]
    by: str
    t: float


@record
class Rest:
    """loop/<key>-rest.json: the loop sleeps until `until` (network down, lanes out)."""

    V: ClassVar[int] = 1
    until: float
    why: str
    t: float = 0.0


@record
class BadVersion:
    """An install that failed its selftest or crashed a run."""

    version: str
    why: str
    t: float


@record
class BadVersions:
    """bad-versions.json."""

    V: ClassVar[int] = 1
    entries: list[BadVersion] = field(default_factory=list)
