"""Slot custody: one kernel `flock` per managed slot, taken without waiting; the only importer of `process_lock`.

The attempt entry holds its slot's lock around its whole body (preparation, the agent run, the publish retries, the
factory commit, the clean-tree check and the verdict). `tl plan verify` and a repeating `tl plan start` take the same
lock around their Git writes (`hold`). A second taker, in this process or another, is refused at once (`SlotBusy`):
nonreentrant, `timeout=0`. The lock file sits beside the slots (`<slots_root>/<repo_id>/.locks/sN.lock`), outside the
slot, where the agent's sandbox cannot write; nothing ever deletes it. The kernel frees the lock when its holder exits,
so a free lock is never a stop proof for a worker. The holder record (the attempt and the taker's role; the library adds
pid and time) is informational only: nothing decides on it.
"""

from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Final, Literal

from process_lock import LockHeldError, ProcessLock

from taskloop.plan_types import Admission

LABEL: Final = "taskloop-slot"
type Role = Literal["entry", "verify"]


class SlotBusy(Exception):
    """Another holder owns the slot's lock now: nothing was read or written."""


class SlotLockUnavailable(Exception):
    """The lock file or its folder cannot be created or opened."""


class ReadOnly(Exception):
    """A read-only verifier was asked to write Git: a wiring defect, never contention."""


def lock_path(cwd: str) -> Path:
    """The slot's lock file, from the stored reservation path: `<slots_root>/<repo_id>/.locks/<slot name>.lock`."""
    slot = Path(cwd)
    return slot.parent / ".locks" / f"{slot.name}.lock"


def acquire(cwd: str, attempt_id: str, role: Role) -> ProcessLock:
    """Take the slot's lock now or refuse: `SlotBusy` when held (here or elsewhere), `SlotLockUnavailable` on an OS error."""
    try:
        return ProcessLock.acquire(
            lock_path(cwd), timeout=0, label=LABEL, meta={"attempt": attempt_id, "role": role}, reentrant=False
        )
    except LockHeldError as error:
        raise SlotBusy(str(error.path)) from error
    except OSError as error:
        raise SlotLockUnavailable(type(error).__name__) from error


@contextmanager
def hold(admission: Admission) -> Generator[None]:
    """A verifier's Git writes for `admission`, under its slot's lock; released when the block ends, raised or not."""
    lock = acquire(admission.cwd, admission.key.attempt_id, "verify")
    try:
        yield
    finally:
        lock.release()


def refused(_admission: Admission) -> AbstractContextManager[None]:
    """The hold of a read-only verifier, which never writes Git: any write it were asked for fails closed (`ReadOnly`)."""
    raise ReadOnly("read_only")
