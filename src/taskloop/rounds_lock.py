"""One rounds process per (factory.db, backlog): a kernel `flock` on `<factory.db>.rounds-<backlog>.lock` beside
factory.db, taken without waiting and held for the process's life; with slot custody the
only importers of `process_lock`.

A second `tl step rounds` for the same factory.db and backlog is refused at once (`RoundsRunning`, naming the holder
record's pid: informational, nothing decides on it); another backlog has its own lock. One-shot rounds (`tl step next`,
`tl step start`) never take it: the fences make them safe beside it. The kernel frees the lock when its holder exits;
nothing deletes the file.
"""

from pathlib import Path
from typing import Final

from process_lock import LockHeldError, ProcessLock

LABEL: Final = "taskloop-rounds"


class RoundsRunning(Exception):
    """Another rounds process holds this backlog's lock now."""

    def __init__(self, pid: int | None) -> None:
        super().__init__("another `tl step rounds` runs for this backlog" + ("" if pid is None else f" (pid {pid})"))
        self.pid = pid


class RoundsLockUnavailable(Exception):
    """The lock file beside factory.db cannot be created or opened."""


def lock_path(db: Path, backlog: str) -> Path:
    """`<factory.db>.rounds-<backlog>.lock`; the backlog is one plain word (`rounds.inputs`)."""
    return db.with_name(f"{db.name}.rounds-{backlog}.lock")


def hold(db: Path, backlog: str) -> ProcessLock:
    """Take the backlog's rounds lock now or refuse: `RoundsRunning` when held (here or elsewhere), `RoundsLockUnavailable`
    on an OS error."""
    try:
        return ProcessLock.acquire(lock_path(db, backlog), timeout=0, label=LABEL, meta={"backlog": backlog}, reentrant=False)
    except LockHeldError as error:
        raise RoundsRunning(error.pid) from error
    except OSError as error:
        raise RoundsLockUnavailable(type(error).__name__) from error
