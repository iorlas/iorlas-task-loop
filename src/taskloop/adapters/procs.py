"""Child processes through the vendored stream-proc: the one place task-loop spawns, waits for and stops a process tree.

Nothing here (nor anywhere in the repo outside `_vendor/`) sends a signal: a stop is `stream_proc.stop_tree`, a liveness read is
`stream_proc.alive`. A process this program did not spawn (the dashboard server, a recorded lock holder) is stopped through a
`PidHandle`, which gives stop_tree the few attributes of a `Popen` it uses; the process-group detail stays inside stream-proc."""

import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import stream_proc
from stream_proc import TermHold, alive, popen_held, proc_start, stop_tree
from stream_proc.proctable import has_table

from taskloop.adapters.childenv import child_env_of, current_env, script_argv  # noqa: F401  (still spoken as procs.X by the tests)

STOP_GRACE_S = 5.0

__all__ = ["TermHold", "alive", "popen_held", "proc_start", "stop_tree"]


@dataclass(frozen=True)
class Ran:
    exit: int
    out: str
    err: str
    secs: float
    timed_out: bool


def capture(
    argv: list[str],
    cwd: str | None,
    env: Mapping[str, str] | None,
    timeout_s: float,
    tick: Callable[[], None] | None = None,
    poll_s: float = 0.2,
) -> Ran:
    """Run a child to its end (or `timeout_s`), collecting stdout and stderr. `tick` runs every `poll_s` on a helper thread while
    the child lives, and once more after it ends. The tree is stopped on a timeout and on any exception (a raising SIGTERM handler)."""
    out: list[str] = []
    err: list[str] = []
    done = threading.Event()

    def ticker(beat: Callable[[], None]) -> None:
        while not done.wait(poll_s):
            beat()

    helper = threading.Thread(target=ticker, args=(tick,), daemon=True) if tick else None
    if helper:
        helper.start()
    try:
        res = stream_proc.run(argv, cwd=cwd, env=env, on_stdout=out.append, on_stderr=err.append, timeout=timeout_s, grace=STOP_GRACE_S)
    finally:
        done.set()
        if helper:
            helper.join(2)
    if tick:
        tick()
    timed = res.timed_out is not None
    return Ran(
        124 if timed else (res.returncode if res.returncode is not None else -(res.signal or 1)),
        "".join(out),
        "".join(err),
        res.secs,
        timed,
    )


def spawn(argv: list[str] | str, **kw: Any) -> subprocess.Popen[bytes]:
    """A child that outlives this call (a detached server, a digest): through stream-proc's held spawn, in a session of its own."""
    kw.setdefault("start_new_session", True)
    p, hold = popen_held(argv, **kw)
    try:
        hold.replay()  # a SIGTERM that arrived during the spawn runs the real handler now, with the child in hand
    except BaseException:
        stop_tree(p, grace=STOP_GRACE_S)
        raise
    return p


class PidHandle:
    """A running process this program did not spawn, as `stop_tree` wants it: pid, returncode, poll() and wait(). It is the
    process named by (pid, start token) or nothing: a pid that is another process now reads as gone."""

    def __init__(self, pid: int, start: str | None = None) -> None:
        self.pid, self.start = pid, start or proc_start(pid)
        self.returncode: int | None = None
        self.args: list[str] = []

    def poll(self) -> int | None:
        if self.returncode is None and not alive(self.pid, self.start):
            self.returncode = 0
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        end = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if end is not None and time.monotonic() >= end:
                raise subprocess.TimeoutExpired(self.args, timeout or 0)
            time.sleep(0.02)
        return self.returncode or 0


def stop_pid(pid: int, start: str | None = None, grace: float = STOP_GRACE_S) -> tuple[int, ...]:
    """Stop the process (pid, start) and its tree through stream-proc; -> pids still alive after the proof."""
    return stop_tree(PidHandle(pid, start), grace=grace)  # type: ignore[arg-type]


Proc = stream_proc.Proc


def table() -> dict[int, Proc] | None:
    """Every process the system lists, through stream-proc (/proc on Linux, libproc on macOS; no ps, no signal): None where it lists
    none at all (no readable table), so a caller reads that as "cannot tell", never as "nothing runs"."""
    if not has_table():
        return None
    rows = stream_proc.table()
    return rows or None


def stop_in_thread(p: Any, grace: float) -> threading.Thread:
    """`stop_tree` on a thread, so the caller's loop goes on while the tree ends. -> the thread."""
    th = threading.Thread(target=stop_tree, args=(p,), kwargs={"grace": grace}, daemon=True)
    th.start()
    return th
