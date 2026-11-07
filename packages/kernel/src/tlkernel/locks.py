"""Lock records: who holds the engine, a slot ticket, a named lock. Liveness is a pid probe, nothing more."""
from typing import ClassVar, final

import stream_proc

from tlkernel.enums import LockWhat
from tlkernel.wire import Rec


def pid_alive(pid: int, start: str = "") -> bool:
    """True when a process with this pid exists and is no zombie (stream-proc). With `start` (its proc_start token), a pid another
    process took over reads as gone; without, a reused pid is not detected."""
    return pid > 0 and stream_proc.alive(pid, start or None)


class LockTimeout(TimeoutError):
    """A wait for a lock ran out; `holder` is who had it (None when unreadable)."""

    def __init__(self, what: str, holder: LockRecord | None) -> None:
        super().__init__("{} held by {}".format(what, holder.holder if holder else "?"))
        self.holder = holder


@final
class EngineLock(Rec):
    """<config>/locks/engine-<key>.lock: the run-task (or the loop, `by`) that owns the worktree, . A process is named by pid
    and start token (pidcheck.proc_start): a reused pid is not the same process. pid 0: a worker outlived its engine (delegate says so:
    `adapters.agent.running_for`); the lock names no worker."""

    V: ClassVar[int] = 4
    pid: int
    started: float
    start: str = ""
    bead: str = ""
    slot: str = ""
    slot_bead: str = ""
    by: str = "run-task"


@final
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


@final
class LockRecord(Rec):
    """locks/<what>-<id>.lock: who holds a named lock, as JSON."""

    V: ClassVar[int] = 1
    what: LockWhat
    holder: str
    pid: int
    t: float

    def alive(self) -> bool:
        """A holder hint from a dead process cannot represent a held lease."""
        return pid_alive(self.pid)
