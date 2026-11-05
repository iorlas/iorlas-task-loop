"""Wait for another connection to commit without building a dashboard snapshot."""

import sqlite3
import threading
import time
from collections.abc import Callable

from taskloop.contracts import factorydb
from taskloop.contracts.paths import ConfigDir

MAX_WAIT = 25.0
POLL_EVERY = 0.05


def wait_seconds(value: str) -> float:
    """Invalid, negative and NaN waits mean an ordinary immediate read."""
    try:
        return max(0.0, min(float(value), MAX_WAIT))
    except ValueError:
        return 0.0


class Wake:
    def __init__(self, cfg: ConfigDir, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg, self.sleep, self.clock = cfg, sleep, clock
        self.lock = threading.Lock()
        self.con: sqlite3.Connection | None = None
        self.identity: tuple[int, int] | None = None

    def close(self) -> None:
        """Release the connection after requests stop, or before reopening."""
        with self.lock:
            self._close()

    def _close(self) -> None:
        if self.con is not None:
            self.con.close()
        self.con, self.identity = None, None

    def token(self) -> int | None:
        """Read data_version on the same connection, serialized across request threads."""
        with self.lock:
            try:
                stat = self.cfg.factory_db().stat()
                identity = (stat.st_dev, stat.st_ino)
                if self.identity != identity:
                    self._close()
                if self.con is None:
                    self.con = factorydb.open_watch(self.cfg.factory_db())
                    self.identity = identity
                if self.con is None:
                    return None
                return factorydb.change_counter(self.con)
            except (OSError, sqlite3.Error):
                self._close()
                return None

    def wait(self, since: int | None, seconds: float) -> int | None:
        """Check every 50 ms, releasing the connection lock between checks."""
        deadline = self.clock() + max(0.0, min(seconds, MAX_WAIT))
        token = self.token()
        while token is not None and token == since and self.clock() < deadline:
            self.sleep(min(POLL_EVERY, max(0.0, deadline - self.clock())))
            token = self.token()
        return token
