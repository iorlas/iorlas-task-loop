"""The one link to delegate for the engine: `resolve` (the library, its contract), `call`, and the read-only side questions.

delegate is a library (`delegate.api`, the only module of it this package imports): `call` builds one `api.RunRequest`, hands it to the
runner seam, and returns a `DelegateResult`. It never raises (but an interruption): a call that returned nothing is a synthesized
`no_answer`, an answer that breaks the shape a `contract_violation`, a call the engine had to stop a `timeout`. Facts of a synthesized
stop come from delegate's contract.json (`api.contract()`). Nothing here reads prose."""

import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from delegate import api
from taskloop.adapters import delegate_wire
from taskloop.contracts.delegate import REASON_TIMEOUT, DelegateResult, Permanence, RunRequest, Scope
from taskloop.contracts.env import Env

CONTRACT = delegate_wire.CONTRACT  # the contract number this engine speaks
NODE_MARGIN_S = 180  # --timeout passed = the node's limit minus this
BACKSTOP_S = 120  # the engine stops the child at the node's limit plus this
LIBRARY = "delegate.api"  # what the engine logs as the route of a call

Runner = Callable[..., Any]


@dataclass(frozen=True)
class Resolved:
    dir: Path
    route: str
    contract: dict[str, Any]
    source: str  # explicit | pinned | installed


@dataclass(frozen=True)
class Refusal:
    kind: str  # not_installed | pin_unreadable | pin_missing_dir | skew_delegate_newer_no_match | skew_delegate_older
    detail: str = ""


@dataclass(frozen=True)
class Answer:
    """A parsed answer, its checkpoint wire object ({} for a synthesized stop), and the exact call argv and output for diagnostics."""

    res: DelegateResult
    raw: dict[str, Any]
    argv: tuple[str, ...] = ()
    trace: str = ""


class Stopped(Exception):
    """The engine ended the call (its wall limit, its silence watcher). `why` is the engine's own word for it."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def resolve() -> Resolved:
    """The delegate library and its contract. There is nothing to install, pin or refuse: the contract is the one this engine ships with."""
    return Resolved(Path(), LIBRARY, api.contract(), "library")


def _last_json(text: str) -> Any:
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


def lane_status(env: Env | None = None) -> dict[str, Any]:
    """Status `lanes` (name -> {out, out_until, ...}); {} when it cannot be read."""
    lanes = status_json().get("lanes")
    return lanes if isinstance(lanes, dict) else {}


def role_status(env: Env | None = None) -> dict[str, Any]:
    """Status `roles`: {role: {"usable": True | False | None, "lane", "why", "until", ...}}; {} when unreadable."""
    roles = status_json().get("roles")
    return roles if isinstance(roles, dict) else {}


class RouteProbe:
    """delegate's network probe (sockets only). up() -> True, False, or None (the probe could not run)."""

    def __init__(self, hosts: tuple[str, ...] = ()) -> None:
        self.hosts = tuple(hosts)

    def up(self) -> bool | None:
        try:
            return api.network(self.hosts)
        except (Exception, SystemExit):
            return None


def synth_for(contract: Mapping[str, Any], reason: str, default: tuple[Scope, Permanence], text: str, ref: str = "") -> DelegateResult:
    """A stop with no answer to read: the facts are the contract's row for `reason`, else `default` (scope, permanence)."""
    row = (contract.get("reasons") or {}).get(reason)
    if isinstance(row, dict) and "scope" in row:
        scope = delegate_wire.pick(row["scope"], delegate_wire.SCOPES, default[0])
        perm = delegate_wire.pick(row.get("permanence"), delegate_wire.PERMANENCE, default[1])
    else:
        scope, perm = default
    return delegate_wire.synth(reason, scope, perm, text, ref, producer="engine" if reason == "no_answer" else "delegate")


def api_request(req: RunRequest, env: Mapping[str, str]) -> api.RunRequest:
    """The delegate.api form of the engine's request. `env`: the worker's per-call variables ."""
    return api.RunRequest(
        role=req.role, brief_file=req.brief_path, cwd=req.cwd, schema_file=req.schema_path, resume=req.resume or None,
        authored_by=req.authored_by or None, timeout_s=req.timeout_s or None, idle_s=req.idle_s or None, unattended=req.unattended,
        parent=req.parent, task=req.task, title=req.title[:120], call_id=req.call_id or None, live_file=req.live_file or None,
        engine_only=list(req.engine_only), engine_only_advisory=req.engine_only_advisory, only_family=list(req.only_family),
        writer_exec_allow=[list(x) for x in req.writer_exec_allow],
        worker_env=dict(env),
    )


def call(
    resolved: Resolved, req: RunRequest, brief: str, schema: dict[str, Any], runner: Runner, env: Mapping[str, str]
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
            req = req.replace(brief_path=bf, schema_path=sf)
            argv = req.to_argv("python", resolved.route)  # for the trace only: the runner takes `request`
            wall = (req.timeout_s + BACKSTOP_S) if req.timeout_s else None
            p = runner(argv, cwd=req.cwd or None, env=dict(env, **req.env()), timeout=wall, request=api_request(req, env))
    except (Stopped, subprocess.TimeoutExpired) as e:
        why = e.why if isinstance(e, Stopped) else "its wall limit ran out"
        return Answer(
            synth_for(c, REASON_TIMEOUT, ("bead", "transient"), "the engine ended the call: %s" % (why or "its time ran out"), req.resume),
            {},
            tuple(argv), str(e),
        )
    except (OSError, ValueError) as e:
        return Answer(synth_for(c, "no_answer", ("machine", "transient"), f"delegate could not run: {e}", req.resume), {},
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
                req.resume,
            ),
            {},
            tuple(argv), trace,
        )
    return Answer(delegate_wire.result_of(j), j, tuple(argv), trace)
