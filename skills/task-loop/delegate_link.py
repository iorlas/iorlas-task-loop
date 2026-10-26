"""The one link to delegate's route.py: which install, the handshake file, and `call` (60-design-A3 sec 2.1; tl-7y6.4.3).

`resolve` picks the install in A3's order (an explicit path, the `pinned.json` entry, then `installed_plugins.json` user scope;
never a glob over the cache) and refuses a contract it does not speak (contract 3: every answer carries `stop`, null = done).
`call` runs one `route.py run`, never raises, and always returns either `stop is None` (done) or a `lane_policy.Stop`: a
process that printed nothing is a synthesized `no_answer`, an answer that breaks the shape a synthesized `contract_violation`,
a call the engine had to stop a synthesized `timeout`. The stop's facts come from the answer's `stop{}` and the install's
contract.json, not from literals here (the three synthesized reasons have no answer to read). Argument discipline: only flags
contract.json lists in `run_args` are passed. Nothing here reads prose. Python 3.8+, stdlib only.
"""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import lane_policy as lp
import tl
from core import procs

CONTRACT = 3            # the contract number this engine speaks (R20 and R21 are one pair)
NODE_MARGIN_S = 180     # --timeout passed = the node's timeout minus this
BACKSTOP_S = 120        # the engine kills the child at the node's timeout plus this
PLUGIN = "iorlas-delegate@"


@dataclass(frozen=True)
class Resolved:
    dir: Path
    route: str
    contract: dict
    source: str          # explicit | pinned | installed


@dataclass(frozen=True)
class Refusal:
    kind: str            # not_installed | pin_unreadable | pin_missing_dir | skew_delegate_newer_no_match | skew_delegate_older
    detail: str = ""


@dataclass
class CallRequest:
    role: str
    brief: str
    schema: dict
    cwd: str
    resume: str = ""
    authored_by: str = ""
    task: str = ""
    parent: str = ""
    title: str = ""
    timeout_s: int = 0
    call_id: str = ""
    live: str = ""   # the file delegate appends the worker's live events to (DELEGATE_LIVE_FILE); the dashboard's Live view reads it


@dataclass
class CallResult:
    data: object = None
    text: str = ""
    say: str = ""
    ref: str = ""
    lane: str = ""
    model: str = ""
    family: str = ""
    run_id: str = ""
    call_id: str = ""
    cost: float = 0.0
    secs: float = 0.0
    usage: dict = field(default_factory=dict)
    stop: object = None            # lane_policy.Stop, None iff done
    source: str = "delegate"       # delegate | synthesized
    raw: dict = field(default_factory=dict)

    @property
    def done(self):
        return self.stop is None


class Stopped(Exception):
    """The engine ended the call (its wall limit, its write-idle watcher). `why` is the engine's own word for it."""

    def __init__(self, why):
        super().__init__(why)
        self.why = why


class ProcRunner:
    """The `runner` seam over core.procs.run_proc: the engine's log, the write-idle watcher and the kill record
    (`stop`, `obs`: why the call was ended, the pids that outlived it, the process boundaries). One per call."""

    def __init__(self, log_path, idle=None, wall=None):
        self.log_path, self.idle, self.wall = log_path, idle, wall   # wall: the limit that holds while a write's activity cannot be seen
        self.stop, self.obs, self.secs = {}, {}, 0.0

    def __call__(self, cmd, **kw):
        res, self.secs = procs.run_proc(cmd, kw.get("cwd"), self.wall or kw.get("timeout") or 3600, self.log_path, idle=self.idle,
                                        stop=self.stop, obs=self.obs, env=kw.get("env"))
        if res is None:
            raise Stopped(self.stop.get("why") or "timeout")
        return subprocess.CompletedProcess(cmd, res[0], res[1], "")


def read_contract_file(path):
    try:
        j = json.loads(Path(path).read_text(encoding="utf-8"))
        return j if isinstance(j, dict) and isinstance(j.get("reasons"), dict) else None
    except (OSError, ValueError):
        return None


def read_contract(d):
    return read_contract_file(Path(d) / "skills" / "delegate" / "contract.json")


def installed_dir(claude_dir=None):
    """The user-scope install `installed_plugins.json` records for delegate, or None."""
    try:
        recs = json.loads(((Path(claude_dir) if claude_dir else tl.claude_dir()) / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        for key, entries in (recs.get("plugins") or {}).items():
            if key.startswith(PLUGIN):
                for e in entries:
                    if e.get("scope") == "user" and e.get("installPath"):
                        return Path(e["installPath"])
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return None


def resolve(path="", pinned=None, installed=None, contract=CONTRACT):
    """-> Resolved | Refusal. path: an explicit delegate dir or its route.py (a dev override or the `delegate` config key);
    pinned: the pinned dir (default tl's); installed: the installed dir (default installed_plugins.json). A pin that is gone is
    a refusal, never a fall-through."""
    if path:
        d, source = Path(path), "explicit"
        route = str(d) if d.suffix == ".py" else str(d / "skills" / "delegate" / "route.py")
        c = read_contract_file(Path(route).with_name("contract.json"))
    else:
        pin = pinned if pinned is not None else tl.pinned_dir("delegate")
        if pin:
            d, source = Path(pin), "pinned"
            if not d.is_dir():
                return Refusal("pin_missing_dir", str(d))
        else:
            d, source = (installed if installed is not None else installed_dir()), "installed"
            if not d:
                return Refusal("not_installed")
        route = str(d / "skills" / "delegate" / "route.py")
        c = read_contract(d)
    if c is None:
        return Refusal("pin_unreadable" if source == "pinned" else "not_installed", str(d))
    have = int(c.get("contract") or 0)
    if have > contract:
        return Refusal("skew_delegate_newer_no_match", "delegate speaks contract %d, this engine %d" % (have, contract))
    if have < contract:
        return Refusal("skew_delegate_older", "delegate speaks contract %d, this engine %d" % (have, contract))
    return Resolved(d.parent if d.suffix == ".py" else d, route, c, source)


def role_status(route, timeout=60):
    """`route.py status --json` roles{}: {role: {"usable": True | False | None, "lane", "why", "until", ...}}; {} when it cannot be read.
    Read-only: delegate holds the truth about a role, a caller only looks."""
    try:
        r = subprocess.run([sys.executable, route, "status", "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=procs.child_env())
        j = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    roles = j.get("roles") if isinstance(j, dict) else None
    return roles if isinstance(roles, dict) else {}


def facts_of(contract, reason, default):
    """(scope, permanence, retry kind) of a reason as the install's contract.json states it; default when it lists none."""
    r = (contract.get("reasons") or {}).get(reason)
    return (r["scope"], r["permanence"], r["retry"]) if isinstance(r, dict) and "scope" in r else default


def wording_of(contract, reason):
    r = (contract.get("reasons") or {}).get(reason)
    return str(r.get("wording") or "") if isinstance(r, dict) else ""


def _synth(contract, reason, default, text, **kw):
    """A stop with no answer to read: the facts are the contract's row for `reason`, else `default`."""
    s, p, k = facts_of(contract, reason, default)
    return CallResult(text=text[-2000:], say=text[:300], stop=lp.Stop(s, p, k, reason=reason, **kw), source="synthesized")


def stop_of(contract, j):
    """The lane_policy.Stop of a non-done answer. Facts: the answer's `stop{}`; else the install's reason table; else a tuple
    the policy does not know (it pauses the lane). The reason string is wording. One exception, named: a `killed` stop is a
    signal (contract 3 states no signal number, and (machine, transient, none) alone cannot tell it from a crash)."""
    st = j.get("stop") if isinstance(j.get("stop"), dict) else {}
    ref = str(j.get("ref") or st.get("ref") or (j.get("usage") or {}).get("ref") or "")
    reason = str(st.get("reason") or "")
    if st.get("scope") and st.get("permanence"):
        s, p, k = st["scope"], st["permanence"], (st.get("retry") or {}).get("kind") or "none"
    else:
        s, p, k = facts_of(contract, reason, ("unknown", "unknown", "unknown"))
    at = (st.get("retry") or {}).get("at") or 0.0
    sig = int(st.get("signal") or 0) or (1 if reason == "killed" else 0)
    return lp.Stop(s, p, k, float(at), reason, bool(st.get("resumable", False)), bool(st.get("partial", False)), ref,
                   str(j.get("lane") or ""), str(j.get("model") or ""), sig, str(st.get("fix") or ""), str(st.get("fingerprint") or ""))


def real_denied(j):
    """The refusals that count: contract 3 lists `sandbox_limit` ones (a system resource the sandbox blocks) but they are noise."""
    return [d for d in (j.get("denied") or []) if isinstance(d, dict) and d.get("kind") != "sandbox_limit"]


def argv_of(resolved, req, brief_file, schema_file):
    """The `route.py run` command. Every flag is listed in contract.json run_args (the caller's test asserts it)."""
    cmd = [sys.executable, resolved.route, "run", req.role, "--brief", brief_file, "--cwd", req.cwd, "--schema", schema_file,
           "--unattended", "--parent", req.parent, "--task", req.task, "--title", req.title[:120]]
    if req.timeout_s:  # a short call (a reflection) passes its whole limit; a node passes its limit less the margin
        cmd += ["--timeout", str(req.timeout_s - NODE_MARGIN_S if req.timeout_s > 2 * NODE_MARGIN_S else req.timeout_s)]
    for flag, val in (("--resume", req.resume), ("--authored-by", req.authored_by), ("--call-id", req.call_id)):
        if val:
            cmd += [flag, val]
    return cmd


def answer_of(contract, j, resume=""):
    """The CallResult of a parsed answer object (contract 3: `contract` is the number, `stop` is null or the facts)."""
    if j.get("contract") != CONTRACT or "stop" not in j or not (j["stop"] is None or isinstance(j["stop"], dict)):
        return _synth(contract, "contract_violation", ("machine", "needs_owner", "none"),
                      "an answer that is not contract %d: %s" % (CONTRACT, json.dumps(j)[:300]), ref=str(j.get("ref") or resume))
    usage = j.get("usage") if isinstance(j.get("usage"), dict) else {}
    r = CallResult(j.get("data"), str(j.get("text") or ""), str(j.get("say") or ""), str(j.get("ref") or usage.get("ref") or ""),
                   str(j.get("lane") or ""), str(j.get("model") or ""), str(j.get("family") or ""), str(j.get("run_id") or ""),
                   str(j.get("call_id") or ""), float(j.get("cost") or 0), float(j.get("secs") or 0), usage, None, "delegate", j)
    if j["stop"] is not None:
        r.stop = stop_of(contract, j)
    return r


def call(resolved, req, runner=subprocess.run, env=None):
    """One delegate call. Never raises (but an interruption: BaseException goes on). runner(cmd, **kw) -> CompletedProcess is
    the process seam; it raises Stopped (or TimeoutExpired) when the call had to be ended."""
    c = resolved.contract
    try:
        with tempfile.TemporaryDirectory() as d:
            bf, sf = os.path.join(d, "brief.md"), os.path.join(d, "schema.json")
            Path(bf).write_text(req.brief, encoding="utf-8")
            Path(sf).write_text(json.dumps(req.schema), encoding="utf-8")
            if req.live:
                env = {**(os.environ if env is None else env), "DELEGATE_LIVE_FILE": req.live}
            kw = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=req.cwd or None, env=env)
            if req.timeout_s:
                kw["timeout"] = req.timeout_s + BACKSTOP_S
            p = runner(argv_of(resolved, req, bf, sf), **kw)
    except (Stopped, subprocess.TimeoutExpired) as e:
        return _synth(c, "timeout", ("bead", "transient", "none"), "the engine ended the call: %s" % (getattr(e, "why", "") or "its time ran out"),
                      ref=req.resume)
    except (OSError, ValueError) as e:
        return _synth(c, "no_answer", ("machine", "transient", "none"), "route.py could not run: %s" % e, ref=req.resume)
    out = (p.stdout or "").strip()
    try:
        j = json.loads(out.splitlines()[-1]) if out else None
    except ValueError:
        j = None
    if not isinstance(j, dict):
        return _synth(c, "no_answer", ("machine", "transient", "none"), "route.py exit %s, no answer object: %s" % (p.returncode, out or p.stderr or ""),
                      ref=req.resume)
    return answer_of(c, j, req.resume)
