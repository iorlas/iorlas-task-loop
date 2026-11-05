"""The one public module of delegate: `run`, `status`, `cancel`, typed. task-loop imports this and nothing else of delegate
(.importlinter); delegate imports nothing of task-loop. A delegate fault is a failed RunResult, never an exception.

Workers stay child processes in their own process group; `cancel` stops one by its Handle (SIGTERM, then SIGKILL after the grace).
One call at a time per process: `run` sets DELEGATE_LIVE_FILE for its duration.
"""

import os
from collections.abc import Callable

from delegate.adapters import procs
from delegate.app import answer, env
from delegate.app import run as run_app
from delegate.app import status as status_app
from delegate.cli import parser
from delegate.contracts import codec, wire
from delegate.contracts import status as status_wire
from delegate.contracts.codec import record
from delegate.contracts.json_types import Json
from delegate.contracts.status import Status
from delegate.contracts.wire import RunRequest, RunResult, ToolServer, WorkerEnd

__all__ = ["Handle", "RunRequest", "RunResult", "Status", "ToolServer", "WorkerEnd", "cancel", "run", "status"]


@record
class Handle:
    """A launched worker: with the pid, `start` names one process, so a recycled pid is never signalled."""

    run_id: str
    pid: int
    pgid: int
    start: str | None


def _failed(request: RunRequest, say: str) -> RunResult:
    obj = answer.result("crash", say=say, call_id=request.call_id)
    return codec.from_json(RunResult, obj)


def run(request: RunRequest, started: Callable[[Handle], None] | None = None) -> RunResult:
    """One worker call, end to end. `started` receives the Handle the moment the worker exists (to `cancel` it later)."""
    contract: dict[str, Json] = {"contract": wire.CONTRACT, "capabilities": list(wire.CAPABILITIES)}
    live_before = os.environ.get("DELEGATE_LIVE_FILE")
    try:
        args = parser.build().parse_args(request.to_argv("route.py", contract=contract)[2:])  # [python, route.py, "run", ROLE, ...]
        os.environ.update(request.env())
        call = run_app.Run(args, env.load_routing(), unattended=request.unattended, idle_s=request.idle_s, log=lambda line: None)
        if started:
            call.on_started = lambda run_id, w: started(Handle(run_id=run_id, pid=w.pid, pgid=w.pgid, start=w.start))
        return codec.from_json(RunResult, call.call())
    except (Exception, SystemExit) as error:
        return _failed(request, f"{type(error).__name__}: {error}")
    finally:
        if live_before is None:
            os.environ.pop("DELEGATE_LIVE_FILE", None)
        else:
            os.environ["DELEGATE_LIVE_FILE"] = live_before


def status() -> Status:
    """The full lane status (probes the fleet and leaves the snapshot)."""
    payload, _lanes, _ck = status_app.full_status(env.load_routing())
    return codec.from_json(status_wire.Status, payload)


def cancel(handle: Handle) -> WorkerEnd:
    """Stop the worker and its tree. A worker that already ended is a clean WorkerEnd."""
    return procs.kill_tree(procs.Orphan(procs.Worker(pid=handle.pid, pgid=handle.pgid, start=handle.start)))
