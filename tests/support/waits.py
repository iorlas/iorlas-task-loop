"""Wait for a condition, not for a fixed time: poll quickly, give up at a limit that only a broken test reaches."""
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
