"""One writer at a time on a file family: the vendored ProcessLock (a kernel flock, dropped when its process dies), taken
non-reentrant so a second thread of one process waits like a second process does. Contracts cannot reach adapters/locks.py
(layers) and the dashboard imports contracts only, so the read-modify-write stores take this one directly."""
import contextlib
from collections.abc import Generator
from pathlib import Path

from process_lock import ProcessLock


@contextlib.contextmanager
def guard(path: Path) -> Generator[None]:
    """Wait for the lock file `path` and hold it for the `with` block. Never nest on one path: the second take waits forever."""
    with ProcessLock.acquire(path, timeout=None, reentrant=False):
        yield
