"""Wait for a condition, not for a fixed time: poll quickly, give up at a limit that only a broken test reaches."""
import time


def until(predicate, limit=10.0, poll=0.005):
    """The predicate's first truthy answer, or None at the limit."""
    end = time.monotonic() + limit
    while True:
        got = predicate()
        if got:
            return got
        if time.monotonic() >= end:
            return None
        time.sleep(poll)
