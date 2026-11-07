"""The one public module of delegate: `run`, `status`, `cancel`, typed. task-loop imports this and nothing else of delegate
(.importlinter); delegate imports nothing of task-loop. A delegate fault is a failed RunResult, never an exception.

Workers stay child processes in their own process group; `cancel` stops one by its Handle (SIGTERM, then SIGKILL after the grace).
One call at a time per process: `run` sets the request's environment (DELEGATE_LIVE_FILE, worker_env) for its duration.
"""

import json
import os
from collections.abc import Callable
from dataclasses import replace

from stream_proc import proc_start

from delegate.adapters import procs
from delegate.app import answer, doctor, env, net, threads
from delegate.app import run as run_app
from delegate.app import status as status_app
from delegate.cli import parser
from delegate.contracts import codec, wire
from delegate.contracts import status as status_wire
from delegate.contracts.codec import record
from delegate.contracts.history import RunRow
from delegate.contracts.json_types import Json, as_str
from delegate.contracts.status import Status
from delegate.contracts.wire import RunRequest, RunResult, ToolServer, WorkerEnd

__all__ = [
    "Account",
    "AgentRef",
    "Handle",
    "RunRequest",
    "RunResult",
    "Status",
    "ToolServer",
    "WorkerEnd",
    "accounts",
    "agents",
    "as_json",
    "cancel",
    "contract",
    "history",
    "network",
    "run",
    "set_account",
    "status",
]


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
    wanted = request.env()
    before = {k: os.environ.get(k) for k in wanted}
    try:
        os.environ.update(wanted)
        planned = threads.plan(request, env.load_state(), env.typed_routing(env.load_routing())) if request.thread else None
        res = _run(request, started, contract, planned)
        if planned and planned.resume and threads.needs_fresh(res):
            env.update_state(lambda state: state.threads.pop(planned.key, None))
            fresh = threads.plan(replace(request, thread="", resume=None), env.load_state(), env.typed_routing(env.load_routing()))
            takeover = request.role == "worker"
            fresh = replace(
                fresh, key=planned.key, brief_text=fresh.brief_text + (threads.TAKEOVER_NOTE if takeover else ""), takeover=takeover
            )
            res = threads.merge(res, _run(request, started, contract, fresh))
        if planned:
            env.update_state(lambda state: threads.settle(state, planned.key, res))
        return res
    except (Exception, SystemExit) as error:
        return _failed(request, f"{type(error).__name__}: {error}")
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run(
    request: RunRequest,
    started: Callable[[Handle], None] | None,
    contract: dict[str, Json],
    planned: threads.ThreadPlan | None,
) -> RunResult:
    effective = replace(request, resume=planned.resume) if planned else request
    args = parser.build().parse_args(effective.to_argv("route.py", contract=contract)[2:])
    call = run_app.Run(
        args,
        env.load_routing(),
        unattended=request.unattended,
        idle_s=request.idle_s,
        brief=planned.brief_text if planned else None,
        log=lambda line: None,
    )
    if started:
        call.on_started = lambda run_id, w: started(Handle(run_id=run_id, pid=w.pid, pgid=w.pgid, start=w.start))
    return codec.from_json(RunResult, call.call())


def status(claude_usage: Json = None) -> Status:
    """The full lane status (probes the fleet and leaves the snapshot). `claude_usage`: the Claude plan's usage windows, when the caller
    has them (the status line is the only place a headless run can read them from)."""
    payload, _lanes, _ck = status_app.full_status(env.load_routing(), claude_usage)
    return codec.from_json(status_wire.Status, payload)


@record
class Account:
    """One lane of the fleet: whether the router may use it, whether this machine can run it, and what fixes it when it cannot."""

    lane: str
    enabled: bool
    ready: bool
    fix: str


@record
class AgentRef:
    """A worker run that still goes: the run, the task it serves (the caller's `task`), where, and in what role."""

    run_id: str
    task: str
    lane: str
    role: str


def agents() -> list[AgentRef]:
    """The runs whose worker or whose route process is still alive, by the leases delegate keeps: the answer for a caller that restarted
    (an engine killed with its worker running). Reads only; the reap of an orphan stays at the next claim."""
    found = []
    for run_id, v in env.load_state().leases.items():
        worker = v.worker_pid is not None and bool(v.worker_start) and proc_start(v.worker_pid) == v.worker_start
        route = bool(v.pid_start) and proc_start(v.pid) == v.pid_start
        if worker or route:
            found.append(AgentRef(run_id=run_id, task=v.task, lane=v.lane, role=v.role or ""))
    return found


def history(since: float = 0.0) -> list[dict[str, Json]]:
    """The finished worker runs after `since` (epoch seconds), oldest first, as wire objects (ts, role, task, lane, model, tokens, ...).
    The only way to read them: the file is delegate's."""
    return [codec.to_json(r) for r in env.history_store().rows(since) if isinstance(r, RunRow)]


def accounts() -> list[Account]:
    """Every lane with its state: the setup view. `fix` names the one step that makes a lane ready (a login, a CLI)."""
    rows = doctor.lane_rows(env.load_routing())
    return [Account(lane=as_str(r["lane"]), enabled=bool(r["enabled"]), ready=bool(r["ready"]), fix=as_str(r["fix"])) for r in rows]


def set_account(lane: str, enabled: bool) -> None:
    """The owner's choice for a lane: enabled or declined. A lane that is not in the fleet raises ValueError."""
    known = [a.lane for a in accounts()]
    if lane not in known:
        raise ValueError(f"unknown lane {lane}; lanes: {', '.join(known)}")
    doctor.config_set(f"profile.lanes.{lane}", "enabled" if enabled else "declined")


def as_json(record: Status | RunResult) -> dict[str, Json]:
    """The wire form of a result or status (the JSON object `route.py` used to print): for a caller that stores or forwards it."""
    return codec.to_json(record)


def contract() -> dict[str, Json]:
    """contract.json: the reasons a stop carries and their facts, the capabilities, the answer schema."""
    return json.loads((env.DATA_DIR / "contract.json").read_text(encoding="utf-8"))


def network(hosts: tuple[str, ...] = ()) -> bool:
    """Whether the vendor hosts (else all of them) are reachable now; sockets only, no worker, no quota."""
    return bool(net.net_probe(list(hosts) or None)["up"])


def cancel(handle: Handle) -> WorkerEnd:
    """Stop the worker and its tree. A worker that already ended is a clean WorkerEnd."""
    return procs.kill_tree(procs.Orphan(procs.Worker(pid=handle.pid, pgid=handle.pgid, start=handle.start)))
