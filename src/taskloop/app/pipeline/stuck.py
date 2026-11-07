"""The engine's stuck tick: at every Beat (and once more before the Close) the run's own log is read from where the last tick ended and
the StuckWatch (domain/stuck.py) says whether a new stuck episode began; each one is written as one Stuck record."""

import contextlib
import threading
from typing import Protocol

from tlkernel.docstore import Page
from tlkernel.log import EngineLog, Stuck

from taskloop.adapters.agent import last_event_t
from taskloop.domain.stuck import StuckWatch


class StuckReader(Protocol):
    def read_from(self, offset: int) -> Page[EngineLog]: ...


class StuckLog(Protocol):
    @property
    def log(self) -> StuckReader: ...

    def emit(self, rec: Stuck) -> int: ...


class StuckHost(Protocol):
    @property
    def live_now(self) -> str: ...

    @property
    def log(self) -> StuckLog: ...

    def now(self) -> float: ...


class StuckTick:
    def __init__(self, host: StuckHost) -> None:
        self.host = host
        self.watch = StuckWatch()
        self.offset = 0
        self.lock = threading.Lock()  # the Beat thread and the close-out may tick at once

    def worker_t(self) -> float:
        """When the worker of the open call last wrote its live file (0 when there is none)."""
        path = self.host.live_now
        return last_event_t(path) if path else 0.0

    def tick(self) -> None:
        host = self.host
        with self.lock, contextlib.suppress(OSError):
            page = host.log.log.read_from(self.offset)
            for item in page.items:
                self.watch.feed(item.rec)
            self.offset = page.cursor
            self.watch.saw(self.worker_t())
            for rec in self.watch.tick(host.now()):
                host.log.emit(rec)  # no Warn beside it: any other record is activity, and would end the episode it reports
