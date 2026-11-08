"""delegate's route.py for the race test (contract 4): plan one stage, the worker writes f-<bead>.txt after a seeded
pause, the review passes. Each worker call appends a witness line to $FAKE_ROUTE_LOG: the worktree's branch and engine
lock at its start and end, so a reset under a live engine shows."""

import hashlib
import json
import os
import random
import sqlite3
import subprocess
import sys
import time


def opt(args, flag):
    return args[args.index(flag) + 1] if flag in args else ""


def read_lock(cwd):
    """The engine lock of the worktree `cwd` as a dict: its `lease` row `run` `engine:<folder>-<8 hex of sha1 of its real path>` in
    <config>/factory.db, else an older tl's locks/engine-<key>.lock file; {} when there is none."""
    real = os.path.realpath(cwd)
    key = f"{os.path.basename(real)}-{hashlib.sha1(real.encode()).hexdigest()[:8]}"
    base = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "task-loop")
    try:
        con = sqlite3.connect(f"file:{os.path.join(base, 'factory.db')}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT body FROM lease WHERE kind='run' AND name=?", ("engine:" + key,)).fetchone()
        finally:
            con.close()
        if row:
            return json.loads(row[0])
    except sqlite3.Error, ValueError:
        pass
    try:
        with open(os.path.join(base, "locks", f"engine-{key}.lock"), encoding="utf-8") as f:
            return json.load(f)
    except OSError, ValueError:
        return {}


def lock_pid(cwd):
    return read_lock(cwd).get("pid")


def branch(cwd):
    return subprocess.run(
        ["git", "symbolic-ref", "--short", "-q", "HEAD"], cwd=cwd, capture_output=True, text=True, check=False
    ).stdout.strip()


def main(a):
    if a[0] == "status":
        print(json.dumps({"v": 1, "accounts": {}, "roles": {}}))
        return 0
    if a[0] == "net":
        print(json.dumps({"v": 1, "up": True, "ip_up": True, "why": "", "ms": 1, "hosts": [], "at": 0, "since": None}))
        return 0
    cwd, bead = opt(a, "--cwd"), opt(a, "--task")
    with open(opt(a, "--schema"), encoding="utf-8") as f:
        props = json.load(f).get("properties", {})
    name = f"f-{bead}.txt"
    if "stages" in props:
        node, data = (
            "plan",
            {
                "summary": "add " + name,
                "stages": [
                    {
                        "goal": "add " + name,
                        "files": [name],
                        "checks": [{"kind": "adhoc", "argv": ["test", "-f", name], "reads": []}],
                        "hard": False,
                    }
                ],
                "risks": [],
                "question": "",
                "options": [],
                "decided": "",
                "cases": [],
                "leftovers": [],
            },
        )
    elif "checks_run" in props:
        node = "write"
        start = {"t": time.time(), "branch": branch(cwd), "lock": lock_pid(cwd)}
        rnd = random.Random(f"{os.environ.get('RACE_SEED', '0')}-{bead}")
        time.sleep(rnd.uniform(0.5, 2.0))
        with open(os.path.join(cwd, name), "w") as f:
            f.write(bead + "\n")
        time.sleep(rnd.uniform(0.0, 0.5))
        with open(os.environ["FAKE_ROUTE_LOG"], "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "bead": bead,
                        "cwd": os.path.realpath(cwd),
                        "pid": os.getpid(),
                        "engine": os.getppid(),
                        "start": start,
                        "end": {"t": time.time(), "branch": branch(cwd), "lock": lock_pid(cwd)},
                    }
                )
                + "\n"
            )
        data = {
            "summary": "wrote " + name,
            "checks_run": [{"cmd": "test -f " + name, "exit": 0}],
            "question": "",
            "options": [],
            "decided": "",
            "bad_checks": [],
            "new_cases": [],
            "unchecked": [],
            "logic_only": "",
        }
    else:
        node, data = (
            "review",
            {
                "findings": [],
                "unmet": [],
                "question": "",
                "criteria": [{"item": "A1", "status": "met", "evidence": "the check passes"}],
                "options": [],
                "decided": "",
                "leftovers": [],
                "unchecked": [],
                "look": "",
            },
        )
    ref, family = f"ref-{node}-{bead}", "openai" if node == "write" else "claude"
    tokens = {"in": 1, "cached": 0, "out": 1}
    print(
        json.dumps(
            {
                "contract": 4,
                "data": data,
                "text": "ok",
                "say": "",
                "ref": ref,
                "account": "L",
                "model": "m",
                "effort": "e",
                "family": family,
                "flag": None,
                "fallback": False,
                "first_account": "L",
                "rung": 0,
                "tokens": tokens,
                "cost": 0.0,
                "secs": 1,
                "run_id": "race",
                "call_id": "race",
                "denied": [],
                "git_violation": [],
                "warnings": [],
                "usage": {"tokens": tokens, "cost": 0.0, "secs": 1, "turns": 1, "context_k": None, "answer_bytes": 0, "ref": ref},
                "stop": None,
                "resumed": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
