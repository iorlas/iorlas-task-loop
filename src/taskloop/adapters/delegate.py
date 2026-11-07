"""The one link to delegate for the engine: `resolve` (the library, its contract), `call`, and the read-only side questions.

delegate is a library (`delegate.api`, the only module of it this package imports): `call` builds one `api.RunRequest`, hands it to the
runner seam, and returns a `DelegateResult`. It never raises (but an interruption): a call that returned nothing is a synthesized
`no_answer`, an answer that breaks the shape a `contract_violation`, a call the engine had to stop a `timeout`. Facts of a synthesized
stop come from delegate's contract.json (`api.contract()`). Nothing here reads prose."""

import contextlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, override

from delegate import api
from taskloop.adapters import delegate_wire
from taskloop.adapters.runner import ApiRunner
from tlkernel.delegate import REASON_TIMEOUT, DelegateResult, Permanence, RunRequest, Scope, WorkerStarted
from tlkernel.delegate_status import snapshot_of
from tlkernel.delegateport import Account, Answer, Lane, Refusal, Resolved, RunRecord, Seam, Stopped
from tlkernel.snapshots import StatusSnapshot

CONTRACT = delegate_wire.CONTRACT  # the contract number this engine speaks
BACKSTOP_S = 120  # the engine stops the child at the node's limit plus this
LIBRARY = "delegate.api"  # what the engine logs as the route of a call

Runner = Callable[..., Any]


def resolve() -> Resolved:
    """The delegate library and its contract. There is nothing to install, pin or refuse: the contract is the one this engine ships with."""
    return Resolved(Path(), LIBRARY, api.contract(), "library")


def _last_json(text: str) -> object:
    try:
        return json.loads(text.strip().splitlines()[-1]) if text.strip() else None
    except (ValueError, IndexError):
        return None


def status_json(claude_usage: Any = None) -> dict[str, Any]:
    """delegate's status answer (the `status --json` object); {} when it cannot be built."""
    try:
        return dict(api.as_json(api.status(claude_usage)))
    except (Exception, SystemExit):  # a delegate with no config or no login is an empty status, not a crash of the caller
        return {}


def status_snapshot(claude_usage: object = None) -> StatusSnapshot:
    """delegate's status read into the StatusSnapshot the dashboard files. ValueError when there is none or its shape is unreadable."""
    status = status_json(claude_usage)
    if not status:
        raise ValueError("delegate status could not be built")
    return snapshot_of(status)


def lanes() -> list[Lane]:
    """Every lane delegate knows, in its order. [] when the status cannot be read."""
    raw = status_json().get("lanes")
    out: list[Lane] = []
    for name, row in (raw.items() if isinstance(raw, dict) else []):
        v = row if isinstance(row, dict) else {}
        usable = None if v.get("out") is None else not v["out"]
        out.append(Lane(str(name), usable, str(v.get("reason") or ""), float(v.get("out_until") or 0.0)))
    return out


def lane(name: str) -> Lane | None:
    """The lane `name`, or None when delegate has no such lane here."""
    return next((x for x in lanes() if x.name == name), None)


def run_history(since: float = 0.0) -> list[RunRecord]:
    """delegate's finished runs after `since` (`api.history`): the one read of them."""
    return [dict(r) for r in api.history(since)]


def accounts() -> list[Account]:
    """Every lane with its state (enabled, ready, the fix). Raises what delegate raises when it has no config dir."""
    return [Account(a.lane, a.enabled, a.ready, a.fix) for a in api.accounts()]


def set_account(lane: str, enabled: bool) -> None:
    api.set_account(lane, enabled)


class RouteProbe:
    """delegate's network probe (sockets only). up() -> True, False, or None (the probe could not run)."""

    def __init__(self, hosts: tuple[str, ...] = ()) -> None:
        self.hosts = tuple(hosts)

    def up(self) -> bool | None:
        try:
            return api.network(self.hosts)
        except (Exception, SystemExit):
            return None


def synth_for(contract: Mapping[str, Any], reason: str, default: tuple[Scope, Permanence], text: str) -> DelegateResult:
    """A stop with no answer to read: the facts are the contract's row for `reason`, else `default` (scope, permanence)."""
    row = (contract.get("reasons") or {}).get(reason)
    if isinstance(row, dict) and "scope" in row:
        scope = delegate_wire.pick(row["scope"], delegate_wire.SCOPES, default[0])
        perm = delegate_wire.pick(row.get("permanence"), delegate_wire.PERMANENCE, default[1])
    else:
        scope, perm = default
    return delegate_wire.synth(reason, scope, perm, text, "", producer="engine" if reason == "no_answer" else "delegate")


def api_request(req: RunRequest, env: Mapping[str, str]) -> api.RunRequest:
    """The delegate.api form of the engine's request. `env`: the worker's per-call variables ."""
    return api.RunRequest(
        role=req.role, brief_file=req.brief_path, cwd=req.cwd, schema_file=req.schema_path,
        thread=req.thread, delta_file=req.delta_path or None, boundary=req.boundary,
        authored_by=req.authored_by or None, timeout_s=req.timeout_s or None, idle_s=req.idle_s or None, unattended=req.unattended,
        parent=req.parent, task=req.task, title=req.title[:120], call_id=req.call_id or None, live_file=req.live_file or None,
        engine_only=list(req.engine_only), engine_only_advisory=req.engine_only_advisory, only_family=list(req.only_family),
        writer_exec_allow=[list(x) for x in req.writer_exec_allow],
        read_roots=list(req.read_roots),
        instructions_ref=req.instructions_ref,
        worker_env=dict(env),
        tools=[api.ToolServer(name=t.name, command=list(t.command), bead=t.bead, run=t.run, stage=t.stage, attempt=t.attempt)
               for t in req.tools],
    )


def call(
    resolved: Resolved, req: RunRequest, brief: str, schema: dict[str, Any], runner: Runner,
    env: Mapping[str, str], delta: str | None = None
) -> Answer:
    """One delegate call. Never raises (but an interruption: BaseException goes on). `runner(argv, cwd=, env=, timeout=)` -> an object
    with `.returncode`, `.stdout`, `.stderr`; it raises Stopped when the engine had to end the call."""
    c = resolved.contract
    argv: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as d:
            bf, sf = os.path.join(d, "brief.md"), os.path.join(d, "schema.json")
            Path(bf).write_text(brief, encoding="utf-8")
            Path(sf).write_text(json.dumps(schema), encoding="utf-8")
            df = os.path.join(d, "delta.md") if delta is not None else req.delta_path
            if delta is not None:
                Path(df).write_text(delta, encoding="utf-8")
            req = req.replace(brief_path=bf, schema_path=sf, delta_path=df)
            wire_req = api_request(req, env)
            with contextlib.suppress(ValueError):  # for the trace only (the runner takes `request`); a refused request has none
                argv = wire_req.to_argv(resolved.route, contract=dict(c))
            wall = (req.timeout_s + BACKSTOP_S) if req.timeout_s else None
            p = runner(argv, cwd=req.cwd or None, env=dict(env), timeout=wall, request=wire_req)
    except (Stopped, subprocess.TimeoutExpired) as e:
        why = e.why if isinstance(e, Stopped) else "its wall limit ran out"
        return Answer(
            synth_for(c, REASON_TIMEOUT, ("bead", "transient"), "the engine ended the call: %s" % (why or "its time ran out")),
            {},
            tuple(argv), str(e),
        )
    except (OSError, ValueError) as e:
        return Answer(synth_for(c, "no_answer", ("machine", "transient"), f"delegate could not run: {e}"), {},
                      tuple(argv), str(e))
    out = (p.stdout or "").strip()
    trace = "\n".join(x for x in (p.stdout, p.stderr) if x)
    j = _last_json(out)
    if not isinstance(j, dict):
        return Answer(
            synth_for(
                c,
                "no_answer",
                ("machine", "transient"),
                "delegate exit {}, no answer object: {}".format(p.returncode, out or p.stderr or ""),
            ),
            {},
            tuple(argv), trace,
        )
    return Answer(delegate_wire.result_of(j), j, tuple(argv), trace)


class DelegateRoute:
    """The real `Route`: delegate.api through the module's functions (looked up at call time, so a test may replace one)."""

    contract_no = CONTRACT
    library = LIBRARY

    def resolve(self) -> Resolved | Refusal:
        return resolve()

    def runner(self, log_path: str | Path, wall: float | None = None, live: str = "",
               on_worker: Callable[[WorkerStarted], None] | None = None) -> Seam | None:
        return ApiRunner(log_path, wall, live, on_worker)

    def call(self, resolved: Resolved, req: RunRequest, brief: str, schema: dict[str, Any], runner: Runner,
             env: Mapping[str, str], delta: str | None = None) -> Answer:
        return call(resolved, req, brief, schema, runner, env=env, delta=delta)

    def probe(self, hosts: tuple[str, ...] = ()) -> RouteProbe:
        return RouteProbe(hosts)

    def lane(self, name: str) -> Lane | None:
        return lane(name)

    def status_snapshot(self, claude_usage: object = None) -> StatusSnapshot:
        return status_snapshot(claude_usage)

    def history(self, since: float = 0.0) -> list[RunRecord]:
        return run_history(since)

    def accounts(self) -> list[Account]:
        return accounts()

    def set_account(self, lane: str, enabled: bool) -> None:
        set_account(lane, enabled)


class FixedRoute(DelegateRoute):
    """A delegate that is already chosen: `resolve` answers `resolved`, `runner` hands out `process` (the selftest and the tests)."""

    def __init__(self, resolved: Resolved | Refusal, process: Seam | None = None) -> None:
        self.resolved, self.process = resolved, process

    @override
    def resolve(self) -> Resolved | Refusal:
        return self.resolved

    @override
    def runner(self, log_path: str | Path, wall: float | None = None, live: str = "",
               on_worker: Callable[[WorkerStarted], None] | None = None) -> Seam | None:
        return self.process
