"""The engine's stuck tick: at every Beat (and once more before the Close) the run's own log is read from where the last tick ended and
the StuckWatch (domain/stuck.py) says whether a new stuck episode began; each one is written as one Stuck record."""

import contextlib
import os
import threading
from typing import Any

from taskloop.domain.stuck import StuckWatch


class StuckTick:
    def __init__(self, host: Any) -> None:
        self.e = host
        self.watch = StuckWatch()
        self.offset = 0
        self.lock = threading.Lock()  # the Beat thread and the close-out may tick at once

    def worker_t(self) -> float:
        """When the worker of the open call last wrote its live file (0 when there is none)."""
        path = self.e.live_now
        if not path:
            return 0.0
        try:
            return os.stat(path).st_mtime
        except OSError:
            return 0.0

    def tick(self) -> None:
        e = self.e
        with self.lock, contextlib.suppress(OSError):
            page = e.log.log.read_from(self.offset)
            for item in page.items:
                self.watch.feed(item.rec)
            self.offset = page.cursor
            self.watch.saw(self.worker_t())
            for rec in self.watch.tick(e.now()):
                e.log.emit(rec)  # no Warn beside it: any other record is activity, and would end the episode it reports
