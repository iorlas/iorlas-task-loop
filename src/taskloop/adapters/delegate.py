"""The one link to delegate's route.py for the engine: which install, the handshake file, `call`, and the read-only side commands.

`resolve` picks the install in this order: an explicit path, the `pinned.json` entry, then `installed_plugins.json` user scope (never a
glob over the cache), and refuses a contract it does not speak (contract 3: every answer carries `stop`, null = done). `call` runs one
`route.py run` built by `RunRequest.to_argv` (the only argv builder), never raises (but an interruption), and returns a `DelegateResult`:
a call that printed nothing is a synthesized `no_answer`, an answer that breaks the shape a `contract_violation`, a call the engine had
to stop a `timeout`. Facts of a synthesized stop come from the install's contract.json. Nothing here reads prose."""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskloop.adapters import childenv, delegate_wire, procs
from taskloop.contracts.delegate import REASON_TIMEOUT, DelegateResult, Permanence, RunRequest, Scope
from taskloop.contracts.env import Env
from taskloop.contracts.ids import MARKETPLACE

CONTRACT = delegate_wire.CONTRACT  # the contract number this engine speaks
NODE_MARGIN_S = 180  # --timeout passed = the node's limit minus this
BACKSTOP_S = 120  # the engine stops the child at the node's limit plus this
PLUGIN = "iorlas-delegate@"
STATUS_TIMEOUT_S = 60
NET_TIMEOUT_S = 20  # `route.py net` answers in under 3 s; a hung child is not waited for longer

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


def read_contract_file(path: Path | str) -> dict[str, Any] | None:
    try:
        j = json.loads(Path(path).read_text(encoding="utf-8"))
        return j if isinstance(j, dict) and isinstance(j.get("reasons"), dict) else None
    except (OSError, ValueError):
        return None


def installed_dir(claude_dir: Path) -> Path | None:
    """The user-scope install `installed_plugins.json` records for delegate, or None."""
    try:
        recs = json.loads((claude_dir / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        for key, entries in (recs.get("plugins") or {}).items():
            if key.startswith(PLUGIN):
                for e in entries:
                    if e.get("scope") == "user" and e.get("installPath"):
                        return Path(e["installPath"])
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return None


def resolve(path: str = "", pinned: Path | None = None, installed: Path | None = None) -> Resolved | Refusal:
    """`path`: an explicit delegate dir or its route.py (a dev override or the `delegate` config key); `pinned`: the pinned dir
    (None: no pin); `installed`: the installed dir. A pin that is gone is a refusal, never a fall-through."""
    if path:
        d, source = Path(path), "explicit"
        route = str(d) if d.suffix == ".py" else str(d / "skills" / "delegate" / "route.py")
        c = read_contract_file(Path(route).with_name("contract.json"))
    else:
        if pinned:
            d, source = Path(pinned), "pinned"
            if not d.is_dir():
                return Refusal("pin_missing_dir", str(d))
        else:
            d, source = installed or Path(), "installed"
            if not installed:
                return Refusal("not_installed")
        route = str(d / "skills" / "delegate" / "route.py")
        c = read_contract_file(d / "skills" / "delegate" / "contract.json")
    if c is None:
        return Refusal("pin_unreadable" if source == "pinned" else "not_installed", str(d))
    have = int(c.get("contract") or 0)
    if have > CONTRACT:
        return Refusal("skew_delegate_newer_no_match", f"delegate speaks contract {have}, this engine {CONTRACT}")
    if have < CONTRACT:
        return Refusal("skew_delegate_older", f"delegate speaks contract {have}, this engine {CONTRACT}")
    return Resolved(d.parent if d.suffix == ".py" else d, route, c, source)


def find_route(path: str, pinned: Path | None, cache: Path, installed: Path | None = None) -> str | None:
    """delegate's route.py: `path` when given, else the pinned dir's (None when that dir is gone: a pin never falls back), else the
    install installed_plugins.json records (`installed`), else the newest under `cache` (<claude>/plugins/cache) of our marketplace only."""
    if path:
        return path if os.path.exists(path) else None
    if pinned:
        route = pinned / "skills" / "delegate" / "route.py"
        return str(route) if route.is_file() else None
    if installed and (installed / "skills" / "delegate" / "route.py").is_file():
        return str(installed / "skills" / "delegate" / "route.py")
    found = []
    for p in cache.glob(f"{MARKETPLACE}/iorlas-delegate/*/skills/delegate/route.py"):
        found.append((tuple(int(x) for x in p.parents[2].name.split(".") if x.isdigit())[:3], str(p)))
    return max(found)[1] if found else None


def _last_json(text: str) -> Any:
    try:
        return json.loads(text.strip().splitlines()[-1]) if text.strip() else None
    except (ValueError, IndexError):
        return None


def _status(route: str, env: Env) -> dict[str, Any]:
    ran = procs.capture([sys.executable, route, "status", "--json"], None, childenv.current_env(env), STATUS_TIMEOUT_S)
    j = _last_json(ran.out) if ran.exit == 0 else None
    return j if isinstance(j, dict) else {}


def lane_status(route: str, env: Env) -> dict[str, Any]:
    """`route.py status --json` lanes (name -> {out, out_until, ...}); {} when it cannot be read."""
    lanes = _status(route, env).get("lanes")
    return lanes if isinstance(lanes, dict) else {}


def role_status(route: str, env: Env) -> dict[str, Any]:
    """`route.py status --json` roles{}: {role: {"usable": True | False | None, "lane", "why", "until", ...}}; {} when unreadable."""
    roles = _status(route, env).get("roles")
    return roles if isinstance(roles, dict) else {}


class RouteProbe:
    """delegate's `route.py net`: {"up": bool, ...} as the last stdout line. up() -> True, False, or None (the probe could not run)."""

    def __init__(self, route: str, hosts: tuple[str, ...] = ()) -> None:
        self.route, self.hosts = route, tuple(hosts)

    def up(self) -> bool | None:
        cmd = [sys.executable, self.route, "net"]
        for h in self.hosts:
            cmd += ["--host", h]
        j = _last_json(procs.capture(cmd, None, None, NET_TIMEOUT_S).out)
        return bool(j["up"]) if isinstance(j, dict) and "up" in j else None


def synth_for(contract: Mapping[str, Any], reason: str, default: tuple[Scope, Permanence], text: str, ref: str = "") -> DelegateResult:
    """A stop with no answer to read: the facts are the contract's row for `reason`, else `default` (scope, permanence)."""
    row = (contract.get("reasons") or {}).get(reason)
    if isinstance(row, dict) and "scope" in row:
        scope = delegate_wire.pick(row["scope"], delegate_wire.SCOPES, default[0])
        perm = delegate_wire.pick(row.get("permanence"), delegate_wire.PERMANENCE, default[1])
    else:
        scope, perm = default
    return delegate_wire.synth(reason, scope, perm, text, ref)


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
            argv = req.replace(brief_path=bf, schema_path=sf).to_argv(sys.executable, resolved.route)
            wall = (req.timeout_s + BACKSTOP_S) if req.timeout_s else None
            p = runner(argv, cwd=req.cwd or None, env=dict(env, **req.env()), timeout=wall)
    except (Stopped, subprocess.TimeoutExpired) as e:
        why = e.why if isinstance(e, Stopped) else "its wall limit ran out"
        return Answer(
            synth_for(c, REASON_TIMEOUT, ("bead", "transient"), "the engine ended the call: %s" % (why or "its time ran out"), req.resume),
            {},
            tuple(argv), str(e),
        )
    except (OSError, ValueError) as e:
        return Answer(synth_for(c, "no_answer", ("machine", "transient"), f"route.py could not run: {e}", req.resume), {},
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
                "route.py exit {}, no answer object: {}".format(p.returncode, out or p.stderr or ""),
                req.resume,
            ),
            {},
            tuple(argv), trace,
        )
    return Answer(delegate_wire.result_of(j), j, tuple(argv), trace)
