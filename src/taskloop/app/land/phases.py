"""A timed step per phase of a land-stack item (fetch, gate, push, PR, merge, record, cleanup, the land lock's wait), so
`tl runs show RUN` and `tl runs slow` say where a land's time goes. A phase is a step_start / step_end pair named `land:<phase>`; its
end carries the seconds (exec for work, wait for the lock)."""
import contextlib
import time
from collections.abc import Generator

from taskloop.contracts import log as rec
from taskloop.stores.runlog import RunLog


@contextlib.contextmanager
def phase(log: RunLog, name: str, *, wait: bool = False) -> Generator[None]:
    """Time the body as the step `land:<name>`; its seconds are `wait_seconds` for a wait, else `exec_seconds`."""
    step = f"land:{name}"
    sid = log.next_id("s")
    log.emit(rec.StepStart(id=sid, step=step))
    t0 = time.monotonic()
    outcome = "done"
    try:
        yield
    except BaseException:
        outcome = "failed"
        raise
    finally:
        secs = time.monotonic() - t0
        log.emit(rec.StepEnd(id=sid, step=step, outcome=outcome, wait_seconds=secs if wait else None, exec_seconds=None if wait else secs))
