"""Preserve obsolete database files under a serialized retirement decision."""

from __future__ import annotations

import fcntl
import sqlite3
import time
from pathlib import Path


def quarantine(path: Path) -> Path:
    """Move a database and its WAL/SHM sidecars to <name>.bad-<time_ns>.

    Call only after closing its connections and stopping its writers. This
    primitive does not lock; the opener serializes its version decision below.
    """
    bad = path.with_name(f"{path.name}.bad-{time.time_ns()}")
    path.replace(bad)
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists():
            side.replace(Path(str(bad) + suffix))
    return bad


def quarantine_if_needed(path: Path, versions: frozenset[int]) -> None:
    """Recheck under flock so racing openers retire a given file only once."""
    lock_path = Path(str(path) + ".schema.lock")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            probe = sqlite3.connect(path, isolation_level=None, timeout=5.0)
            try:
                version = int(probe.execute("PRAGMA user_version").fetchone()[0])
            finally:
                probe.close()
            if version in versions:
                quarantine(path)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
