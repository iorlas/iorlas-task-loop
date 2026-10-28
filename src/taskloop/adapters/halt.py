"""The run's stop flag. SIGTERM only sets it; commands, worker calls and waits end on it and the run stops at its next safe point
(Engine.halt_point). Nothing is raised from inside a signal handler."""

from __future__ import annotations

import contextlib
import signal
import threading
import time
from collections.abc import Iterator

RUN_HALT: dict[str, threading.Event | None] = {"ev": None}  # the flag of the run in this process (None: none running)


@contextlib.contextmanager
def halt_on_sigterm() -> Iterator[None]:
    """The SIGTERM handler lives only as long as the run: an engine called in a process that goes on (a test runner, a host) must
    not leave it behind. Off the main thread nothing is installed (signal handlers live there only)."""
    old = None
    if threading.current_thread() is threading.main_thread():
        RUN_HALT["ev"] = halt = threading.Event()
        old = signal.signal(signal.SIGTERM, lambda *_: halt.set())
    try:
        yield
    finally:
        RUN_HALT["ev"] = None
        if old is not None:
            signal.signal(signal.SIGTERM, old)


@contextlib.contextmanager
def stop_deferred(*_: object) -> Iterator[list[bool]]:
    """SIGTERM inside this block is only noted (the yielded list gets an item); the caller stops after it."""
    got: list[bool] = []
    if threading.current_thread() is not threading.main_thread():
        yield got
        return
    old = signal.signal(signal.SIGTERM, lambda *_: got.append(True))
    try:
        yield got
    finally:
        signal.signal(signal.SIGTERM, old)


def nap(halt: threading.Event, secs: float) -> bool:
    """Wait `secs` in slices of a second, or until `halt` is set. -> whether it is set (nap(halt, 0) just looks)."""
    left = secs
    while left > 0 and not halt.is_set():
        time.sleep(min(1.0, left))
        left -= 1.0
    return halt.is_set()
