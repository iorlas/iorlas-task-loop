"""Instances, never module globals: a TtlCache (answers kept for seconds) and a FileCache (a parsed file kept until it changes).
A caller makes one and passes it down; a test passes its own."""

import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


class TtlCache:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.lock = threading.Lock()
        self.items: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: float, make: Callable[[], Any]) -> Any:
        """The value made under `key` less than `ttl` seconds ago, else a fresh one."""
        with self.lock:
            hit = self.items.get(key)
            if hit and self.clock() - hit[0] < ttl:
                return hit[1]
        val = make()
        self.put(key, val)
        return val

    def peek(self, key: str) -> tuple[float, Any] | None:
        with self.lock:
            return self.items.get(key)

    def put(self, key: str, val: Any) -> None:
        with self.lock:
            self.items[key] = (self.clock(), val)

    def drop(self, key: str) -> None:
        with self.lock:
            self.items.pop(key, None)

    def clear(self) -> None:
        with self.lock:
            self.items.clear()


class FileCache:
    """path -> what `load(path)` returned, re-made only when the file's mtime or size changed; the least recently used go first."""

    def __init__(self, limit: int = 500) -> None:
        self.limit = limit
        self.lock = threading.Lock()
        self.items: OrderedDict[str, tuple[tuple[float, int], Any]] = OrderedDict()

    def get(self, path: str, load: Callable[[str], Any], missing: Any = None) -> Any:
        try:
            st = os.stat(path)
        except OSError:
            with self.lock:
                self.items.pop(path, None)
            return missing
        key = (st.st_mtime, st.st_size)
        with self.lock:
            hit = self.items.get(path)
            if hit and hit[0] == key:
                self.items.move_to_end(path)
                return hit[1]
        val = load(path)
        with self.lock:
            self.items[path] = (key, val)
            self.items.move_to_end(path)
            while len(self.items) > self.limit:
                self.items.popitem(last=False)
        return val
