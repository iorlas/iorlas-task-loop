"""Held logs: one open :class:`JsonlLog` per path per process, so an append skips the open and close (tl-64i: 14 ms vs 0.04 ms on a Mac).

- A log belongs to the process that opened it: after a fork the child closes its copy of the inherited ones and opens its own.
- At most ``MAX_OPEN`` are kept; the least recently used one is evicted: its descriptor closes, but the log stays
  usable, so a thread still holding it reopens the descriptor for its next append and closes it again
  right after (:meth:`JsonlLog.release_fd`). Eviction never raises ``LogClosedError`` in another thread.
- The key is the resolved path. Options apply on first sight; a later ``held`` of the same path with other
  options raises ``ValueError`` rather than silently ignoring them.
- A path whose file was removed or replaced is reopened by the log itself (one stat per append).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, cast

from jsonl_log import JsonlLog

MAX_OPEN = 16


def _key(path: Path | str) -> str:
    return str(Path(path).resolve())


class HeldLogs:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._logs: dict[str, tuple[int, JsonlLog, dict[str, object]]] = {}  # least recently used first

    def get(self, path: Path | str, options: dict[str, object]) -> JsonlLog:
        key, pid = _key(path), os.getpid()
        with self._lock:
            entry = self._logs.pop(key, None)
            if entry is not None and (entry[0] != pid or entry[1].closed):
                entry[1].close()  # an inherited descriptor closes only this process's copy
                entry = None
            elif entry is not None and entry[2] != options:
                self._logs[key] = entry
                msg = f"{key} is held with options {entry[2]}, asked for {options}"
                raise ValueError(msg)
            if entry is None:
                for k in [k for k, v in self._logs.items() if v[0] != pid]:
                    self._drop(k)
                while len(self._logs) >= MAX_OPEN:
                    self._drop(next(iter(self._logs)), evict=True)
                entry = (pid, JsonlLog.open(key, **cast("dict[str, Any]", options)), dict(options))
            self._logs[key] = entry
            return entry[1]

    def close(self, path: Path | str | None) -> None:
        with self._lock:
            for key in list(self._logs) if path is None else [_key(path)]:
                self._drop(key)

    def count(self, path: Path | str | None) -> int:
        with self._lock:
            pid = os.getpid()
            return sum(1 for k, v in self._logs.items() if v[0] == pid and (path is None or k == _key(path)))

    def _drop(self, key: str, *, evict: bool = False) -> None:
        entry = self._logs.pop(key, None)
        if entry is not None:
            entry[1].release_fd() if evict else entry[1].close()


HELD = HeldLogs()
