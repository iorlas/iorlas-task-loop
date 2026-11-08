"""Processes the native way: the spawn, the tree stop and the captured run are the shelf's `any_agent.procs` (every signal goes through
stream_proc). What lives here is what only delegate has: `Orphan`, a recorded worker with no Popen, and the `WorkerEnd` of the wire contract
made from the shelf's `StopReport`s.
"""

import subprocess
from typing import override

from any_agent import procs as shelf
from any_agent.procs import GRACE_S, StopReport, Worker, run_capture, spawn
from stream_proc import alive

from delegate.contracts import wire

__all__ = ["GRACE_S", "Orphan", "StopReport", "Worker", "kill_tree", "run_capture", "spawn", "stop", "worker_end"]


class Orphan(subprocess.Popen[bytes]):
    """A worker delegate recorded but no longer owns (its route.py was SIGKILLed): a Popen that was never started, so stream_proc.stop_tree
    reads it by pid and start token (`__init__` does not start a process; `__del__` has nothing to reap)."""

    def __init__(self, w: Worker) -> None:  # the parent's __init__ would spawn a child
        self.pid, self.start = w.pid, w.start
        self.returncode: int | None = None

    @override
    def __repr__(self) -> str:  # Popen's reads `args`, which an unstarted one has not got
        return f"Orphan(pid={self.pid})"

    @override
    def __del__(self) -> None:
        pass

    @override
    def poll(self) -> int | None:
        if self.returncode is None and not alive(self.pid, self.start):
            self.returncode = 0
        return self.returncode

    @override
    def wait(self, timeout: float | None = None) -> int:
        return self.poll() or 0


def _end(rep: StopReport) -> wire.WorkerEnd:
    """The wire report of one tree stop."""
    survivors = [wire.Survivor(pid=s.pid, start=s.start) for s in rep.survivors]
    end = wire.END_ERROR if rep.error else wire.END_SURVIVED if survivors else wire.END_OK
    return wire.WorkerEnd(
        end=end, stopped=True, term_sent=rep.term_sent, kill_sent=rep.kill_sent, waited_s=rep.waited_s, survivors=survivors
    )


def stop(p: subprocess.Popen[bytes], grace: float) -> wire.WorkerEnd:
    """Stop `p` and its whole tree. -> the wire report."""
    return _end(shelf.stop(p, grace))


def kill_tree(p: subprocess.Popen[bytes], grace: float | None = None) -> wire.WorkerEnd:
    """Stop the worker `p` (a Popen) and its whole tree. -> the wire report; the caller keeps it."""
    return _end(shelf.kill_tree(p, grace))


def worker_end(stops: list[StopReport], outcome: str | None) -> wire.WorkerEnd:
    """The run's WorkerEnd, from the stops made during it and the run's outcome reason (None = done)."""
    survivors = [wire.Survivor(pid=s.pid, start=s.start) for r in stops for s in r.survivors]
    end = wire.END_SURVIVED if survivors else wire.END_TIMEOUT if outcome == "timeout" else wire.END_ERROR if outcome else wire.END_OK
    return wire.WorkerEnd(
        end=end,
        stopped=bool(stops),
        term_sent=any(r.term_sent for r in stops),
        kill_sent=any(r.kill_sent for r in stops),
        waited_s=round(sum(r.waited_s for r in stops), 2),
        survivors=survivors,
    )
