"""One process owns a path: an exclusive ``flock``, held until the process lets go.

- **Exclusive, non-blocking.** A second process asking for the lock gets
  :class:`LockHeldError` at once, with the holder's pid when it wrote one.
- **Released by the kernel.** A ``flock`` dies with its holder, ``kill -9`` included, so
  there is no stale-lock cleanup and no pid to trust. The pid in the file is a hint for the
  message, nothing more.
- **Re-entrant within a process.** Taking it twice in one process is two handles on one
  descriptor, released at the last :meth:`ProcessLock.release`. Not ``lockf``: a POSIX
  record lock is dropped when *any* descriptor on the file closes, so an unrelated
  ``open().close()`` would end ownership.
- **Not inherited.** The descriptor is close-on-exec (``os.open`` makes it so), so a child
  process does not keep the lock after its parent lets go.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from pathlib import Path

_PID_BYTES = 32


class LockHeldError(Exception):
    """Another process holds the lock on :attr:`path`; :attr:`pid` is its pid when it wrote one."""

    def __init__(self, path: Path, pid: int | None) -> None:
        self.path = path
        self.pid = pid
        holder = f"pid {pid}" if pid is not None else "an unknown process"
        super().__init__(f"{path} is locked by another process ({holder})")


@dataclass
class _Held:
    fd: int
    count: int = 0


_REGISTRY: dict[Path, _Held] = {}
_REGISTRY_LOCK = threading.Lock()


def held() -> frozenset[Path]:
    """The resolved lock-file paths this process holds now."""
    with _REGISTRY_LOCK:
        return frozenset(_REGISTRY)


@dataclass
class ProcessLock:
    """One handle on this process's lock of :attr:`path`. :meth:`release` is idempotent."""

    path: Path
    _released: bool = field(default=False, repr=False)

    @classmethod
    def acquire(cls, path: Path) -> ProcessLock:
        """Lock ``path`` for this process, or raise :class:`LockHeldError`."""
        key = path.resolve()
        with _REGISTRY_LOCK:
            entry = _REGISTRY.get(key)
            if entry is None:
                entry = _Held(fd=_lock(key))
                _REGISTRY[key] = entry
            entry.count += 1
        return cls(path=key)

    def release(self) -> None:
        """Give up this handle; the lock goes when the process's last handle does."""
        if self._released:
            return
        self._released = True
        with _REGISTRY_LOCK:
            entry = _REGISTRY.get(self.path)
            if entry is None:
                return
            entry.count -= 1
            if entry.count == 0:
                del _REGISTRY[self.path]
                os.close(entry.fd)  # closing the descriptor drops the flock

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def _lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        holder = _holder(fd)
        os.close(fd)
        raise LockHeldError(path, holder) from exc
    except BaseException:
        os.close(fd)
        raise
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def _holder(fd: int) -> int | None:
    """The pid the current holder wrote, when it is readable."""
    with contextlib.suppress(OSError, ValueError):
        return int(os.pread(fd, _PID_BYTES, 0).decode().strip())
    return None


__all__ = ["LockHeldError", "ProcessLock", "held"]
