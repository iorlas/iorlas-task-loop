"""LockTable on flock(2): the OS drops a lock when its process dies, the file names the holder (a LockRecord as JSON).

A waiter polls, so it can notice that the holder named in the file is dead while the lock is still held (an orphaned child
kept the descriptor): it then replaces the file, and the orphan keeps a lock on a file nobody reads. A file replaced under a
taker is noticed by comparing inodes after the lock is won, and the taker starts over.
"""
import contextlib
import fcntl
import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from taskloop.contracts import codec, paths
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.locks import LockRecord, pid_alive
from taskloop.stores.api import LockTimeout

POLL = 0.02
SETTLE = 0.05  # a new holder truncates the old record within this; a record that outlives it is not the new holder's


def _read(path: Path) -> LockRecord | None:
    try:
        return codec.from_json(LockRecord, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def _trylock(fd: int) -> bool:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


class FileLockTable:
    def __init__(self, cfg: paths.ConfigDir, alive: Callable[[int], bool] = pid_alive, pid: int | None = None) -> None:
        self.cfg = cfg
        self.alive = alive
        self.pid = os.getpid() if pid is None else pid

    @contextlib.contextmanager
    def hold(self, what: LockWhat, ident: str, holder: str, *, timeout: float | None = None,
             waiting: Callable[[LockRecord | None], None] | None = None) -> Iterator[LockRecord]:
        path = self.cfg.lock_record(what.value, ident)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = self._take(path, timeout, waiting)
        rec = LockRecord(what=what, holder=holder, pid=self.pid, t=time.time())  # pyrefly: ignore[unexpected-keyword]
        try:
            os.ftruncate(fd, 0)
            os.write(fd, json.dumps(codec.to_json(rec)).encode("utf-8"))
            yield rec
        finally:
            with contextlib.suppress(OSError):
                os.ftruncate(fd, 0)
            os.close(fd)  # closing drops the flock

    def _take(self, path: Path, timeout: float | None, waiting: Callable[[LockRecord | None], None] | None) -> int:
        end = None if timeout is None else time.monotonic() + timeout
        told = False
        while True:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
            if _trylock(fd) and self._same_file(fd, path):
                return fd
            cur = _read(path)
            if cur is not None and not self.alive(cur.pid) and self._still(path, cur):
                self._break(fd, path)
            elif waiting is not None and not told:
                told = True
                waiting(cur)
            os.close(fd)
            if end is not None and time.monotonic() >= end:
                raise LockTimeout(path.name, _read(path))
            time.sleep(POLL)

    @staticmethod
    def _same_file(fd: int, path: Path) -> bool:
        """False when the lock was won on a file that was replaced since it was opened."""
        try:
            return os.fstat(fd).st_ino == os.stat(path).st_ino
        except OSError:
            return False

    @staticmethod
    def _still(path: Path, cur: LockRecord) -> bool:
        time.sleep(SETTLE)
        return _read(path) == cur

    @staticmethod
    def _break(fd: int, path: Path) -> None:
        if FileLockTable._same_file(fd, path):
            path.unlink(missing_ok=True)

    def holder(self, what: LockWhat, ident: str) -> LockRecord | None:
        path = self.cfg.lock_record(what.value, ident)
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            return None
        try:
            if _trylock(fd):
                return None  # free: a record left by a crash is not a holder
            return _read(path)
        finally:
            os.close(fd)
