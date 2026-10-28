"""Lock records: who holds the engine, a slot ticket, a named lock. Liveness is a pid probe, nothing more."""
import os
from dataclasses import field
from typing import ClassVar

from taskloop.contracts.codec import record
from taskloop.contracts.enums import LockWhat


def pid_alive(pid: int) -> bool:
    """True when a process with this pid exists (signal 0). A pid reused by another process is not detected here."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class LockTimeout(TimeoutError):
    """A wait for a lock ran out; `holder` is who had it (None when unreadable)."""

    def __init__(self, what: str, holder: "LockRecord | None") -> None:
        super().__init__("%s held by %s" % (what, holder.holder if holder else "?"))
        self.holder = holder


@record
class EngineLock:
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
    workers: list[tuple[int, float]] = field(default_factory=list)

    def alive(self) -> bool:
        return pid_alive(self.pid)


@record
class Ticket:
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


@record
class LockRecord:
    """locks/<what>-<id>.lock: who holds a named lock, as JSON."""

    V: ClassVar[int] = 1
    what: LockWhat
    holder: str
    pid: int
    t: float
