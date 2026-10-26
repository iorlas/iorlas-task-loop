"""The one link to delegate's route.py: which install, the handshake file, and `call` (60-design-A3 sec 2.1; tl-7y6.4.3).

`resolve` picks the install in A3's order (an explicit path, the `pinned.json` entry, then `installed_plugins.json` user scope;
never a glob over the cache) and refuses a contract it does not speak. `call` runs one `route.py run`, never raises, and
always returns either `stop is None` (done) or a `lane_policy.Stop`: a process that printed nothing is a synthesized `crash`,
an answer that breaks the schema is a synthesized `contract_violation`. The stop's facts come from the install's
contract.json, not from literals here. Argument discipline: only flags contract.json lists in `run_args` are passed.
Nothing here reads prose. Unused by the engine until R21. Python 3.8+, stdlib only.
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

CONTRACT = 2            # the contract number this engine speaks; R20/R21 move it to 3
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
    host: bool = False
    task: str = ""
    parent: str = ""
    title: str = ""
    timeout_s: int = 0
    call_id: str = ""


@dataclass
class CallResult:
    status: str = ""
    data: object = None
    text: str = ""
    say: str = ""
    ref: str = ""
    lane: str = ""
    model: str = ""
    run_id: str = ""
    call_id: str = ""
    usage: dict = field(default_factory=dict)
    stop: object = None            # lane_policy.Stop, None iff done
    source: str = "delegate"       # delegate | synthesized
    raw: dict = field(default_factory=dict)


def read_contract(d):
    try:
        j = json.loads((Path(d) / "skills" / "delegate" / "contract.json").read_text(encoding="utf-8"))
        return j if isinstance(j, dict) and isinstance(j.get("reasons"), dict) else None
    except (OSError, ValueError):
        return None


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
    """-> Resolved | Refusal. path: an explicit delegate dir (a dev override); pinned: the pinned dir (default tl's);
    installed: the installed dir (default installed_plugins.json). A pin that is gone is a refusal, never a fall-through."""
    if path:
        d, source = Path(path), "explicit"
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
    c = read_contract(d)
    if c is None:
        return Refusal("pin_unreadable" if source == "pinned" else "not_installed", str(d))
    have = int(c.get("contract") or 0)
    if have > contract:
        return Refusal("skew_delegate_newer_no_match", "delegate speaks contract %d, this engine %d" % (have, contract))
    if have < contract:
        return Refusal("skew_delegate_older", "delegate speaks contract %d, this engine %d" % (have, contract))
    return Resolved(d, str(d / "skills" / "delegate" / "route.py"), c, source)


def facts_of(contract, reason, default):
    """(scope, permanence, retry kind) of a reason as the install's contract.json states it; default when it lists none."""
    r = (contract.get("reasons") or {}).get(reason)
    return (r["scope"], r["permanence"], r["retry"]) if isinstance(r, dict) and "scope" in r else default


def _stop(contract, reason, text, default, **kw):
    s, p, k = facts_of(contract, reason, default)
    return lp.Stop(s, p, k, reason=reason, **kw)


def _synth(contract, reason, default, text, **kw):
    return CallResult(status="stop", text=text[-2000:], say=text[:300], stop=_stop(contract, reason, text, default, **kw), source="synthesized")


def stop_of(contract, j):
    """The lane_policy.Stop of a non-done answer. Facts: the answer's `stop{}`; else the install's reason table; else a tuple
    the policy does not know (it pauses the lane). The reason string is wording."""
    ref = str(j.get("ref") or (j.get("usage") or {}).get("ref") or "")
    st = j.get("stop") if isinstance(j.get("stop"), dict) else {}
    reason = str(st.get("reason") or (contract.get("wire_default") or {}).get(j.get("reason"), j.get("reason")) or "")
    if st.get("scope") and st.get("permanence"):
        s, p, k = st["scope"], st["permanence"], (st.get("retry") or {}).get("kind") or "none"
    else:
        s, p, k = facts_of(contract, reason, ("unknown", "unknown", "unknown"))
    at = (st.get("retry") or {}).get("at") or j.get("retry_after") or 0.0
    return lp.Stop(s, p, k, float(at), reason, bool(st.get("resumable", False)), bool(st.get("partial", False)), ref,
                   str(j.get("lane") or ""), str(j.get("model") or ""), int(st.get("signal") or 0), str(st.get("fix") or ""),
                   str(st.get("fingerprint") or ""))


def argv_of(resolved, req, brief_file, schema_file):
    """The `route.py run` command. Every flag is listed in contract.json run_args (the caller's test asserts it)."""
    cmd = [sys.executable, resolved.route, "run", req.role, "--brief", brief_file, "--cwd", req.cwd, "--schema", schema_file,
           "--unattended", "--parent", req.parent, "--task", req.task, "--title", req.title[:120]]
    if req.timeout_s:
        cmd += ["--timeout", str(max(1, req.timeout_s - NODE_MARGIN_S))]
    for flag, val in (("--resume", req.resume), ("--authored-by", req.authored_by), ("--call-id", req.call_id)):
        if val:
            cmd += [flag, val]
    if req.host:
        cmd.append("--host")
    return cmd


def call(resolved, req, runner=subprocess.run, env=None):
    """One delegate call. Never raises. runner(cmd, **kw) -> CompletedProcess is the process seam."""
    c = resolved.contract
    try:
        with tempfile.TemporaryDirectory() as d:
            bf, sf = os.path.join(d, "brief.md"), os.path.join(d, "schema.json")
            Path(bf).write_text(req.brief, encoding="utf-8")
            Path(sf).write_text(json.dumps(req.schema), encoding="utf-8")
            kw = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=req.cwd or None, env=env)
            if req.timeout_s:
                kw["timeout"] = req.timeout_s + BACKSTOP_S
            p = runner(argv_of(resolved, req, bf, sf), **kw)
    except subprocess.TimeoutExpired:
        return _synth(c, "hung", ("model", "transient", "none"), "the engine backstop killed route.py", ref=req.resume)
    except (OSError, ValueError) as e:
        return _synth(c, "crash", ("machine", "transient", "none"), "route.py could not run: %s" % e, ref=req.resume)
    out = (p.stdout or "").strip()
    try:
        j = json.loads(out.splitlines()[-1]) if out else None
    except ValueError:
        j = None
    if not isinstance(j, dict):
        return _synth(c, "crash", ("machine", "transient", "none"), "route.py exit %s, no answer object: %s" % (p.returncode, out or p.stderr or ""), ref=req.resume)
    if j.get("v") != 2 or "status" not in j:
        return _synth(c, "contract_violation", ("machine", "needs_owner", "none"), "an answer that is not worker-run v2: %s" % out[:300], ref=str(j.get("ref") or req.resume))
    usage = j.get("usage") if isinstance(j.get("usage"), dict) else {}
    r = CallResult(j["status"], j.get("data"), str(j.get("text") or ""), str(j.get("say") or ""), str(j.get("ref") or usage.get("ref") or ""),
                   str(j.get("lane") or ""), str(j.get("model") or ""), str(j.get("run_id") or ""), str(j.get("call_id") or ""), usage, None, "delegate", j)
    if j["status"] != "done":
        r.stop = stop_of(c, j)
    return r
