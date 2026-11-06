"""The dashboard-owned index thread; contracts never start threads."""

import logging
import threading
import time
from collections.abc import Callable

from taskloop.contracts import factorydb
from taskloop.contracts.beadsport import Beads
from taskloop.contracts.paths import ConfigDir
from taskloop_dash.index import Indexer


class Worker:
    def __init__(self, cfg: ConfigDir, repos: Callable[[], list[str]], store_of: Callable[[str], Beads]) -> None:
        self.cfg = cfg
        self.repos, self.store_of = repos, store_of
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="factory-index", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.thread.join()

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                with Indexer(self.cfg, repos=self.repos, store_of=self.store_of) as index:
                    while not self.stop.is_set():
                        started = time.monotonic()
                        index.pass_once()
                        self.stop.wait(max(0, 1 - (time.monotonic() - started)))
            except (OSError, ValueError, factorydb.DatabaseError) as error:
                logging.getLogger(__name__).error("run index unavailable: %s", error)
                self.stop.wait(1)
