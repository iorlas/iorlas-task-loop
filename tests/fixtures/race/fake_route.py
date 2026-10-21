"""delegate's route.py for the race test (worker-run v2): plan one stage, the worker writes f-<bead>.txt after a seeded
pause, the review passes. Each worker call appends a witness line to $FAKE_ROUTE_LOG: the worktree's branch and engine
lock at its start and end, so a reset under a live engine shows."""

import json
import os
import random
import subprocess
import sys
import time

CONTRACT = {"worker_run": 2, "features": ["reason", "next", "context"], "reasons": {}, "lanes": {"codex": {}}}


def opt(args, flag):
    return args[args.index(flag) + 1] if flag in args else ""


def lock_pid(cwd):
    try:
        with open(os.path.join(cwd, ".task", "engine.lock"), encoding="utf-8") as f:
            return json.load(f).get("pid")
    except (OSError, ValueError):
        return None


def branch(cwd):
    return subprocess.run(["git", "symbolic-ref", "--short", "-q", "HEAD"], cwd=cwd, capture_output=True,
                          text=True).stdout.strip()


def main(a):
    if a[0] == "contract":
        print(json.dumps(CONTRACT))
        return 0
    if a[0] == "status":
        print(json.dumps({"lanes": {}}))
        return 0
    cwd, bead = opt(a, "--cwd"), opt(a, "--task")
    with open(opt(a, "--schema"), encoding="utf-8") as f:
        props = json.load(f).get("properties", {})
    name = "f-%s.txt" % bead
    if "stages" in props:
        node, data = "plan", {"summary": "add " + name, "stages": [{"goal": "add " + name, "files": [name],
                                                                   "checks": ["test -f " + name], "hard": False}],
                              "risks": [], "question": "", "decided": "", "cases": [], "leftovers": []}
    elif "checks_run" in props:
        node = "write"
        start = {"t": time.time(), "branch": branch(cwd), "lock": lock_pid(cwd)}
        rnd = random.Random("%s-%s" % (os.environ.get("RACE_SEED", "0"), bead))
        time.sleep(rnd.uniform(0.5, 2.0))
        with open(os.path.join(cwd, name), "w") as f:
            f.write(bead + "\n")
        time.sleep(rnd.uniform(0.0, 0.5))
        with open(os.environ["FAKE_ROUTE_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"bead": bead, "cwd": os.path.realpath(cwd), "pid": os.getpid(), "engine": os.getppid(),
                                "start": start, "end": {"t": time.time(), "branch": branch(cwd),
                                                        "lock": lock_pid(cwd)}}) + "\n")
        data = {"summary": "wrote " + name, "checks_run": [{"cmd": "test -f " + name, "exit": 0}], "question": "",
                "decided": "", "bad_checks": [], "new_cases": [], "unchecked": []}
    else:
        node, data = "review", {"findings": [], "unmet": [], "question": "", "decided": "", "leftovers": [],
                                "unchecked": []}
    print(json.dumps({"v": 2, "status": "done", "reason": None, "next": None, "data": data, "ref": "ref-%s-%s" % (
        node, bead), "cost": 0.0, "secs": 1, "family": "openai" if node == "write" else "claude", "lane": "L",
        "model": "m", "effort": "e", "git_violation": [], "tokens": {"in": 1, "cached": 0, "out": 1},
        "context": {"instructions": [], "env_keys": []}}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
