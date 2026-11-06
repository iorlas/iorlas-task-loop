"""Processes the native way. A worker is spawned as the leader of a session of its own, so its process group is its tree; every stop goes to
stream_proc, the shelf's one place that signals a process. What lives here is what stream_proc does not know: the `Worker` record, the
`StopReport` of one tree stop and the stdin-piped spawn (the brief goes in on stdin). POSIX only."""

import os
import subprocess
import time
from collections.abc import Mapping
from dataclasses import field

import stream_proc
from stream_proc import proc_start

from any_agent._json import mutable, record

GRACE_S = float(os.environ.get("ANY_AGENT_STOP_GRACE") or 5)  # SIGTERM to SIGKILL


@record
class Worker:
    """A running worker as spawned: the pid, its process group (a session leader's group is its pid), its start token."""

    pid: int
    pgid: int
    start: str | None


@record
class Survivor:
    pid: int
    start: str | None


@mutable
class StopReport:
    """One tree stop: SIGTERM always went first, SIGKILL once the grace ran out, `survivors` outlived both, `error` = stream_proc raised."""

    term_sent: bool = True
    kill_sent: bool = False
    waited_s: float = 0.0
    survivors: list[Survivor] = field(default_factory=list)
    error: bool = False


def spawn(
    argv: list[str],
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    *,
    stderr: int = subprocess.PIPE,
    session: bool = True,
) -> tuple[subprocess.Popen[bytes], Worker]:
    """Start the worker as its own session leader (`session`) with piped stdin and stdout; `stderr` is a pipe unless the caller discards it.
    -> (the Popen, the worker's record)."""
    p, hold = stream_proc.popen_held(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, cwd=cwd, env=env, start_new_session=session
    )
    hold.replay()  # a SIGTERM or SIGINT noted during the spawn is delivered now, as without the hold
    return p, Worker(pid=p.pid, pgid=p.pid, start=proc_start(p.pid))


def stop(p: subprocess.Popen[bytes], grace: float) -> StopReport:
    """Stop `p` and its whole tree (stream_proc.stop_tree). -> the report."""
    t0 = time.monotonic()
    rep = StopReport()
    try:
        left = stream_proc.stop_tree(p, grace=grace)
    except Exception:  # noqa: BLE001 - a stop that raised is reported, never allowed to hide the run's own outcome
        rep.error = True
        return rep
    rep.waited_s = round(time.monotonic() - t0, 2)
    rep.kill_sent = bool(left) or rep.waited_s >= grace
    rep.survivors = [Survivor(pid=c, start=proc_start(c)) for c in left]
    return rep


def kill_tree(p: subprocess.Popen[bytes], grace: float | None = None) -> StopReport:
    """Stop the worker `p` and its whole tree. -> the report; the caller keeps it."""
    return stop(p, GRACE_S if grace is None else grace)


def run_capture(
    argv: list[str], timeout: float, *, env: Mapping[str, str] | None = None, cwd: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run to the end with captured text output and no stdin (stream_proc.run: a session of its own; a timeout kills the whole tree).
    -> CompletedProcess; TimeoutExpired on timeout."""
    out: list[str] = []
    err: list[str] = []
    res = stream_proc.run(argv, env=env, cwd=cwd, on_stdout=out.append, on_stderr=err.append, timeout=timeout, grace=GRACE_S)
    if res.timed_out:
        raise subprocess.TimeoutExpired(argv, timeout, "".join(out), "".join(err))
    return subprocess.CompletedProcess(
        argv, -res.signal if res.signal else -1 if res.returncode is None else res.returncode, "".join(out), "".join(err)
    )
