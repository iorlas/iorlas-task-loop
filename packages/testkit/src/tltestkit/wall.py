"""Interrupt a stalled test, with an independent fatal stack-dump backstop."""
import faulthandler
import os
import signal
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType


class HungTest(Exception):
    """A test exceeded its wall-clock allowance."""


@contextmanager
def wall_guard(seconds: float, what: str) -> Iterator[None]:
    """Guard only a POSIX main thread whose SIGALRM is unclaimed."""
    if os.name != "posix" or threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGALRM)
    if previous != signal.SIG_DFL or any(signal.getitimer(signal.ITIMER_REAL)):
        yield
        return

    def expired(signum: int, frame: FrameType | None) -> None:
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        raise HungTest(f'{what} made no progress for {seconds:.0f} s (wall); thread stacks above')

    signal.signal(signal.SIGALRM, expired)
    try:
        faulthandler.dump_traceback_later(seconds + 60, exit=True, file=sys.stderr)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        faulthandler.cancel_dump_traceback_later()
        signal.signal(signal.SIGALRM, previous)
