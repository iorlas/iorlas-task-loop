#!/usr/bin/env python3
"""A stand-in for delegate's route.py at the process level (tl-7y6.4.3): `contract --json`, `net` and `run`, scripted.

Used by tests only; it lives here so the engine's tests and the loop's share one fake. It reads the installed delegate's
contract.json and tests/contract/fixtures (FAKE_ROUTE_DELEGATE: that dir), so a field delegate adds is a field the fake
answers with. FAKE_ROUTE_SCRIPT names a JSON file {"steps": [...], "net": [true|false, ...]}; each `run` takes the next
step: "done", a reason of contract.json ("network"), a fixture stem ("killed_exit_15_25oct"), or {"step": ..., "partial":
true, "data": {...}}. `--resume X` is echoed as the answer's `ref`, a call without one opens "fake-<n>". Every argv is
appended to <script>.log. Exit 0 whenever an answer was printed. Python 3.8+, stdlib only.
"""

import json
import os
import sys
from pathlib import Path


def counter(path):
    p = Path(str(path) + ".n")
    n = int(p.read_text()) if p.exists() else 0
    p.write_text(str(n + 1))
    return n


def answer(delegate, step, ref, resumed):
    d = Path(delegate)
    c = json.loads((d / "skills" / "delegate" / "contract.json").read_text(encoding="utf-8"))
    step = step if isinstance(step, dict) else {"step": step}
    name = step["step"]
    base = {"v": 2, "data": step.get("data"), "text": "", "say": "", "ref": ref, "lane": "FAKE", "model": "fake-1", "tokens": None,
            "cost": 0, "secs": 0.1, "run_id": "fake-run", "call_id": "fake-call", "transcript": None, "transcript_info": None,
            "denied": [], "git_violation": [], "usage": {"tokens": None, "cost": 0, "secs": 0.1, "turns": 1, "context_k": None,
                                                         "answer_bytes": 0, "ref": ref}, "retry_after": None, "stop": None}
    if name == "done":
        return dict(base, status="done", reason=None, next=None, text=step.get("text", "ok"), resumed=resumed)
    fx = d / "tests" / "contract" / "fixtures" / (name + ".json")
    reason = json.loads(fx.read_text(encoding="utf-8"))["expected_reason"] if fx.is_file() else name
    r = c["reasons"][reason]
    wire = r["wire"]
    stop = {"reason": reason, "scope": r["scope"], "permanence": r["permanence"], "retry": {"kind": r["retry"], "at": step.get("at")},
            "resumable": bool(ref) and step.get("resumable", reason == "network"), "partial": bool(step.get("partial")),
            "signal": step.get("signal"), "fix": step.get("fix")}
    return dict(base, status=wire["status"], reason=wire["reason"], next=c["wire_reasons"].get(wire["reason"]), say=r["wording"], stop=stop)


def main(argv):
    cmd, script = argv[0], json.loads(Path(os.environ["FAKE_ROUTE_SCRIPT"]).read_text())
    log = Path(os.environ["FAKE_ROUTE_SCRIPT"] + ".log")
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(argv) + "\n")
    delegate = os.environ["FAKE_ROUTE_DELEGATE"]
    if cmd == "contract":
        c = json.loads((Path(delegate) / "skills" / "delegate" / "contract.json").read_text(encoding="utf-8"))
        print(json.dumps({"worker_run": 2, "contract": c["contract"]}))
    elif cmd == "net":
        nets = script.get("net") or [True]
        up = nets[min(counter(os.environ["FAKE_ROUTE_SCRIPT"] + ".net"), len(nets) - 1)]
        print(json.dumps({"v": 1, "up": up, "ip_up": up, "why": "", "ms": 1, "hosts": [], "at": 0, "since": None}))
    elif cmd == "run":
        n = counter(os.environ["FAKE_ROUTE_SCRIPT"])
        steps = script["steps"]
        resume = argv[argv.index("--resume") + 1] if "--resume" in argv else ""
        print(json.dumps(answer(delegate, steps[min(n, len(steps) - 1)], resume or "fake-%d" % (n + 1), bool(resume))))
    else:
        print("fake_route: no such command %s" % cmd, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
