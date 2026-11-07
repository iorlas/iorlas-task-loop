"""Wait for a condition, not for a fixed time: poll quickly, give up at a limit that only a broken test reaches."""
import subprocess
import time
from threading import Event


def until(predicate, limit=10.0, poll=0.005):
    """The predicate's first truthy answer, or None at the limit."""
    end = time.monotonic() + limit
    while True:
        got = predicate()
        if got:
            return got
        if time.monotonic() >= end:
            return None
        Event().wait(poll)


def settle(index, *, limit=30.0, **kw):
    """Finish an index sweep, failing if repeated passes never settle."""
    assert until(lambda: index.pass_once(**kw), limit=limit), f"indexer did not settle in {limit:g} s"


def until_marker(marker, child, limit=30.0):
    """Wait for a child process to write its marker; a child that exits first fails the test with its stderr."""
    assert until(lambda: marker.exists() or child.poll() is not None, limit=limit), "the child never wrote its marker"
    if not marker.exists():
        try:
            _, stderr = child.communicate(timeout=5)
            err = stderr.decode() if stderr else ""
        except subprocess.TimeoutExpired:
            err = "stderr was unreadable"
        raise AssertionError(f"the child exited ({child.returncode}) before it wrote its marker: {err}")
