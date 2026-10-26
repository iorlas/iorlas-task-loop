#!/usr/bin/env python3
"""A stand-in for delegate's route.py (contract 3), at two levels, for tests only (tl-7y6.4.3).

Process level: `contract --json`, `net` and `run`, scripted. FAKE_ROUTE_SCRIPT names a JSON file {"steps": [...], "net": [true|
false, ...]}; each `run` takes the next step: "done", a reason of contract.json ("network"), a fixture stem ("killed_exit_15_25oct"),
or {"step": ..., "partial": true, "data": {...}, "at": epoch}. `--resume X` is echoed as the answer's `ref`, a call without one opens
"fake-<n>". Every argv is appended to <script>.log. Exit 0 whenever an answer was printed.

In process: `Script`/`DelegateScript`, a `runner` for delegate_link.call (the engine's `make_runner` seam) that answers per node
from queues, the way the engine's own tests need; `stop_answer(reason, ...)` builds one stopped answer. Both build answers from
`answer()`, which reads contract.json, so a field delegate adds is a field the fakes answer with.

The contract comes from FAKE_ROUTE_DELEGATE (a delegate checkout), else the copy in tests/fixtures/delegate3 (tests compare it to a
real checkout when one is there). Python 3.8+, stdlib only.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDORED = HERE.parents[1] / "tests" / "fixtures" / "delegate3"


def delegate_dir():
    return Path(os.environ.get("FAKE_ROUTE_DELEGATE") or VENDORED)


def contract(delegate=None):
    return json.loads((Path(delegate or delegate_dir()) / "skills" / "delegate" / "contract.json").read_text(encoding="utf-8"))


def handshake(delegate=None):
    """What `route.py contract --json` prints."""
    c = contract(delegate)
    return {"contract": c["contract"], "reasons": c["reasons"], "run_args": c["run_args"]}


CONTRACT = handshake()


def stop_of(c, reason, ref="", resumable=None, partial=False, at=None, fix=None, signal=None):
    r = c["reasons"][reason]
    kind = r["retry"]
    stop = {"reason": reason, "scope": r["scope"], "permanence": r["permanence"],
            "retry": {"kind": kind, "at": at if kind in ("predicted", "poll") else None}, "ref": ref}
    if at and kind == "none" and reason not in ("network", "killed"):
        stop["permanence"], stop["retry"] = "transient", {"kind": "predicted", "at": at}
    if reason in ("network", "killed"):
        stop.update(resumable=bool(ref) and (reason == "network" if resumable is None else resumable), partial=bool(partial))
    if fix:
        stop["fix"] = fix
    if signal:
        stop["signal"] = signal
    return stop


def answer(c, reason, ref="", resumed=False, data=None, text="ok", **kw):
    """One contract-3 answer. reason None = done. kw: resumable, partial, at, fix, signal go to the stop; the rest overrides a field."""
    stop_kw = {k: kw.pop(k) for k in ("resumable", "partial", "at", "fix", "signal") if k in kw}
    base = {"contract": c["contract"], "data": data, "text": text if reason is None else "", "say": "", "ref": ref, "lane": "FAKE",
            "model": "fake-1", "effort": "e", "family": "openai", "flag": None, "fallback": False, "first_lane": "FAKE", "rung": 0,
            "tokens": None, "cost": 0, "secs": 0.1, "run_id": "fake-run", "call_id": "fake-call", "transcript": None,
            "transcript_info": None, "denied": [], "git_violation": [], "warnings": [],
            "usage": {"tokens": None, "cost": 0, "secs": 0.1, "turns": 1, "context_k": None, "answer_bytes": 0, "ref": ref},
            "stop": None, "resumed": resumed}
    if reason is not None:
        base["say"] = c["reasons"][reason]["wording"]
        base["stop"] = stop_of(c, reason, ref, **stop_kw)
    base.update(kw)
    return base


def stop_answer(reason, ref="", delegate=None, **kw):
    """A stopped answer for a test that hands one to Script: the row of `reason` in contract.json, plus kw (see answer)."""
    return answer(contract(delegate), reason, ref, **kw)


def step_answer(delegate, step, ref, resumed):
    c = contract(delegate)
    step = step if isinstance(step, dict) else {"step": step}
    name = step["step"]
    if name == "done":
        return answer(c, None, ref, resumed, step.get("data"), step.get("text", "ok"))
    fx = Path(delegate) / "tests" / "contract" / "fixtures" / (name + ".json")
    reason = json.loads(fx.read_text(encoding="utf-8"))["expected_stop"]["reason"] if fx.is_file() else name
    return answer(c, reason, ref, resumed, step.get("data"), partial=step.get("partial", False), at=step.get("at"),
                  fix=step.get("fix"), signal=step.get("signal"),
                  **({"resumable": step["resumable"]} if "resumable" in step else {}))


def counter(path):
    p = Path(str(path) + ".n")
    n = int(p.read_text()) if p.exists() else 0
    p.write_text(str(n + 1))
    return n


def main(argv):
    cmd, script = argv[0], json.loads(Path(os.environ["FAKE_ROUTE_SCRIPT"]).read_text())
    log = Path(os.environ["FAKE_ROUTE_SCRIPT"] + ".log")
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(argv) + "\n")
    delegate = delegate_dir()
    if cmd == "contract":
        print(json.dumps(handshake(delegate)))
    elif cmd == "net":
        nets = script.get("net") or [True]
        up = nets[min(counter(os.environ["FAKE_ROUTE_SCRIPT"] + ".net"), len(nets) - 1)]
        print(json.dumps({"v": 1, "up": up, "ip_up": up, "why": "", "ms": 1, "hosts": [], "at": 0, "since": None}))
    elif cmd == "run":
        n = counter(os.environ["FAKE_ROUTE_SCRIPT"])
        steps = script["steps"]
        resume = argv[argv.index("--resume") + 1] if "--resume" in argv else ""
        print(json.dumps(step_answer(delegate, steps[min(n, len(steps) - 1)], resume or "fake-%d" % (n + 1), bool(resume))))
    else:
        print("fake_route: no such command %s" % cmd, file=sys.stderr)
        return 2
    return 0


def opt(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else ""


class Script:
    """The in-process route.py: a `runner(cmd, **kw)` for delegate_link.call. Answers per node from queues; a write creates f.txt
    in the worktree like a real writer. answers: {node: [data | a full answer dict (has "contract")]}; j_extra: {node: [fields the
    next done answer gains]}. calls: (role, resume, authored_by) per call; prompts, cwds, schemas, timeouts per call."""

    def __init__(self, answers, j_extra=None, delegate=None):
        self.answers, self.calls, self.prompts, self.cwds, self.timeouts = {k: list(v) for k, v in answers.items()}, [], [], [], []
        self.j_extra = {k: list(v) for k, v in (j_extra or {}).items()}  # per node, per call: fields the answer gains
        self.c = contract(delegate)
        self.nodes = []

    def node_of(self, schema):
        import engine  # the engine sends each contract in strict form, a visual stage's with its look field too
        return next(k for k in engine.SCHEMAS if schema in (engine.strict(engine.schema_for(k)), engine.strict(engine.schema_for(k, True))))

    def __call__(self, cmd, **kw):
        role, cwd = cmd[3], opt(cmd, "--cwd")
        prompt = Path(opt(cmd, "--brief")).read_text(encoding="utf-8")
        schema = json.loads(Path(opt(cmd, "--schema")).read_text(encoding="utf-8"))
        node = self.node_of(schema)
        resume = opt(cmd, "--resume")
        self.calls.append((role, resume or None, opt(cmd, "--authored-by") or None))
        self.nodes.append(node)
        self.cwds.append(cwd)
        self.prompts.append(prompt)
        self.timeouts.append(kw.get("timeout"))
        a = self.answers[node].pop(0)
        if callable(a):
            a = a(self, node, cwd, resume)
        if isinstance(a, dict) and a.get("contract") is not None:
            j = a
        else:
            if node == "write":
                Path(cwd, "f.txt").write_text("d%d\n" % len(self.calls))
            j = answer(self.c, None, "ref-" + node, bool(resume), a, cost=0.5, secs=1, family="openai" if node == "write" else "claude",
                       lane="L", model="m", tokens={"in": 1000, "cached": 800, "out": 50},
                       context={"instructions": ["/repo/AGENTS.md"], "env_keys": ["PATH"]})
            if self.j_extra.get(node):
                j.update(self.j_extra[node].pop(0))
        return subprocess.CompletedProcess(cmd, 0, json.dumps(j), "")


DelegateScript = Script


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
