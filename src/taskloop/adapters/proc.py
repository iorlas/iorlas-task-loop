"""Run one child in its own process group, wait with a deadline, stop the whole group on timeout (POSIX)."""
import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

TERM_GRACE_S = 5.0


@dataclass(frozen=True)
class Ran:
    exit: int
    out: str
    err: str
    secs: float
    timed_out: bool


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except OSError:
        pass


def stop_group(p: subprocess.Popen[bytes]) -> None:
    """TERM the child's group, KILL it after a grace; only a group this module started (p is its leader)."""
    _signal_group(p.pid, signal.SIGTERM)
    try:
        p.wait(timeout=TERM_GRACE_S)
    except subprocess.TimeoutExpired:
        _signal_group(p.pid, signal.SIGKILL)
        p.wait()


def run_group(argv: list[str], cwd: str | None, env: Mapping[str, str] | None, timeout_s: float,
              tick: Callable[[], None] | None = None, poll_s: float = 0.2) -> Ran:
    """stdout and stderr go to temp files, so a chatty child never blocks on a full pipe. `tick` runs every `poll_s`
    while the child lives, and once more after it ends."""
    t0 = time.monotonic()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        p = subprocess.Popen(argv, cwd=cwd, env=None if env is None else dict(env), stdin=subprocess.DEVNULL,
                             stdout=out, stderr=err, start_new_session=True)
        timed_out = False
        try:
            while True:
                try:
                    p.wait(timeout=poll_s)
                    break
                except subprocess.TimeoutExpired:
                    if tick:
                        tick()
                    if time.monotonic() - t0 >= timeout_s:
                        timed_out = True
                        stop_group(p)
                        break
        except BaseException:
            stop_group(p)
            raise
        if tick:
            tick()
        out.seek(0)
        err.seek(0)
        return Ran(124 if timed_out else p.returncode, out.read().decode("utf-8", "replace"),
                   err.read().decode("utf-8", "replace"), time.monotonic() - t0, timed_out)
