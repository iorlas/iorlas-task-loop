"""Stop a process this program did not spawn, named by (pid, start token)."""

from __future__ import annotations

import subprocess
import time

from stream_proc import proctable
from stream_proc.tree import stop_tree


class PidHandle:
    """A running process we did not spawn, with the few ``Popen`` attributes :func:`stop_tree` uses.

    It is the process named by (pid, start token) or nothing: once the pid belongs to another process, or the
    token never matched, ``poll()`` reads it as gone. ``start`` defaults to the token the pid has now.
    """

    def __init__(self, pid: int, start: str | None = None) -> None:
        self.pid = pid
        self.start = start or proctable.proc_start(pid)
        self.returncode: int | None = None
        self.args: list[str] = []

    def poll(self) -> int | None:
        if self.returncode is None and not proctable.alive(self.pid, self.start):
            self.returncode = 0
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        end = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if end is not None and time.monotonic() >= end:
                raise subprocess.TimeoutExpired(self.args, timeout or 0)
            time.sleep(0.02)
        return self.returncode or 0


def stop_pid(pid: int, start: str | None = None, *, grace: float = 5.0, prove: float = 2.0) -> tuple[int, ...]:
    """Stop process ``pid`` and its tree if, and only if, it still has start token ``start``; returns pids left alive.

    ``start=None`` takes the token the pid has now. A pid that is gone, a zombie, or another process (a different
    token) is not touched: ``()``. Without a process table the token cannot be read, so nothing is stopped.
    """
    handle = PidHandle(pid, start)
    if handle.start is None or handle.poll() is not None:
        return ()
    return stop_tree(handle, grace=grace, prove=prove)  # type: ignore[arg-type]
