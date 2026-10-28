"""Locks on the vendored ProcessLock: one holder at a time across processes (and across threads of one), dropped by the
kernel when its process dies, so there is no stale-lock cleanup and no pid to trust.

ProcessLock is non-blocking and re-entrant within a process; a wait is a poll here, and a per-path mutex keeps two threads
of one process out of each other (the race tests are threads). Who holds a lock is a hint for a waiter's message: a
`<lock>.holder` file (a LockRecord as JSON) written after the lock is won and removed before it is let go.
"""
import contextlib
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from atomic_io import atomic_write_json
from process_lock import LockHeldError, ProcessLock, held

from taskloop.contracts import codec, paths
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.locks import LockRecord, LockTimeout

POLL = 0.01
POLL_MAX = 0.1
_MUTEXES: dict[Path, threading.Lock] = {}
_MUTEXES_LOCK = threading.Lock()


def _mutex(key: Path) -> threading.Lock:
    with _MUTEXES_LOCK:
        return _MUTEXES.setdefault(key, threading.Lock())


def holder_file(path: Path) -> Path:
    return path.with_name(path.name + ".holder")


def read_holder(path: Path, pid: int | None = None) -> LockRecord | None:
    """The record the holder wrote; when it has not written one yet (or never does), only its pid, as `pid N`."""
    try:
        return codec.from_json(LockRecord, json.loads(holder_file(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None if pid is None else LockRecord(what=LockWhat.LAND, holder="pid %d" % pid, pid=pid, t=0.0)  # pyrefly: ignore[unexpected-keyword]


@contextlib.contextmanager
def hold_path(path: Path | str, holder: str, *, what: LockWhat = LockWhat.LAND, timeout: float | None = None,
              waiting: Callable[[LockRecord | None], None] | None = None) -> Iterator[LockRecord]:
    """Wait for the lock on `path` (forever, or `timeout` seconds, then LockTimeout), hold it for the `with` block.
    `waiting` is called once, before the first wait, with the current holder (None when unknown)."""
    key = Path(path).resolve()
    mutex, end, told, delay = _mutex(key), None if timeout is None else time.monotonic() + timeout, False, POLL
    while True:
        blocker: LockRecord | None
        if mutex.acquire(blocking=False):
            try:
                lock = ProcessLock.acquire(key)
                break
            except LockHeldError as e:
                mutex.release()
                blocker = read_holder(key, e.pid)
        else:
            blocker = read_holder(key)
        if not told and waiting is not None:
            told = True
            waiting(blocker)
        if end is not None and time.monotonic() >= end:
            raise LockTimeout(key.name, blocker)
        time.sleep(delay)
        delay = min(delay * 2, POLL_MAX)
    rec = LockRecord(what=what, holder=holder, pid=os.getpid(), t=time.time())  # pyrefly: ignore[unexpected-keyword]
    try:
        with contextlib.suppress(OSError):
            atomic_write_json(holder_file(key), codec.to_json(rec), fsync=False)
        yield rec
    finally:
        holder_file(key).unlink(missing_ok=True)
        lock.release()
        mutex.release()


class ProcessLockTable:
    """LockTable over hold_path: the named locks of one ConfigDir."""

    def __init__(self, cfg: paths.ConfigDir) -> None:
        self.cfg = cfg

    def hold(self, what: LockWhat, ident: str, holder: str, *, timeout: float | None = None,
             waiting: Callable[[LockRecord | None], None] | None = None) -> contextlib.AbstractContextManager[LockRecord]:
        return hold_path(self.cfg.lock_record(what.value, ident), holder, what=what, timeout=timeout, waiting=waiting)

    def holder(self, what: LockWhat, ident: str) -> LockRecord | None:
        path = self.cfg.lock_record(what.value, ident).resolve()
        if path in held():
            return read_holder(path)
        try:
            ProcessLock.acquire(path).release()
        except LockHeldError as e:
            return read_holder(path, e.pid)
        return None
