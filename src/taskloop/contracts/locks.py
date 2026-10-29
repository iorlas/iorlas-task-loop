"""Lock records: who holds the engine, a slot ticket, a named lock. Liveness is a pid probe, nothing more."""
from typing import ClassVar

import msgspec
import stream_proc

from taskloop.contracts.enums import LockWhat
from taskloop.contracts.wire import Rec


def pid_alive(pid: int) -> bool:
    """True when a process with this pid exists and is no zombie (stream-proc). A pid reused by another process is not detected here."""
    return pid > 0 and stream_proc.alive(pid)


class LockTimeout(TimeoutError):
    """A wait for a lock ran out; `holder` is who had it (None when unreadable)."""

    def __init__(self, what: str, holder: LockRecord | None) -> None:
        super().__init__("{} held by {}".format(what, holder.holder if holder else "?"))
        self.holder = holder


class EngineLock(Rec):
    """<worktree>/.task/engine.lock: the run-task process that owns the worktree, with the processes it started."""

    V: ClassVar[int] = 2
    pid: int
    bead: str
    started: float
    by: str = ""
    pid_start: float | None = None
    slot: str | None = None
    slot_bead: str | None = None
    route: tuple[int, float] | None = None
    workers: list[tuple[int, float]] = msgspec.field(default_factory=list)

    def alive(self) -> bool:
        return pid_alive(self.pid)


class Ticket(Rec):
    """slots/<repo_key>/<seq>.json: a place in the line for a slot."""

    V: ClassVar[int] = 1
    pid: int
    why: str
    since: float
    prio: int
    seq: int
    pid_start: float | None = None
    bead: str = ""  # the bead the waiter wants a slot for, when it has one (a loop waits before it has picked)

    def alive(self) -> bool:
        return pid_alive(self.pid)


class LockRecord(Rec):
    """locks/<what>-<id>.lock: who holds a named lock, as JSON."""

    V: ClassVar[int] = 1
    what: LockWhat
    holder: str
    pid: int
    t: float
