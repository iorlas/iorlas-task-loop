"""delegate's route.py: finding it, its lane status and handshake, the roles (moved unchanged from engine.py, E2)."""
import json
import os
import re
import subprocess
import sys

import tl
from core import procs


ROLES = {"plan": "planner", "write": "worker", "review": "reviewer", "verify": "reviewer", "look": "reviewer"}  # reviewer: read-only rungs


def find_route(path=""):
    """delegate's route.py: `path` when given (engine.delegate), else the delegate `pinned.json` names (None when that
    dir is gone: a pin never falls back), else the newest installed delegate. Whether it speaks worker-run v2 is the
    handshake's to say (contract)."""
    if path:
        return path if os.path.exists(path) else None
    pinned = tl.pinned_dir("delegate")
    if pinned:
        route = pinned / "skills" / "delegate" / "route.py"
        return str(route) if route.is_file() else None
    found = []
    for p in (tl.claude_dir() / "plugins" / "cache").glob("*/iorlas-delegate/*/skills/delegate/route.py"):
        found.append((tuple(int(x) for x in re.findall(r"\d+", p.parents[2].name)[:3]), str(p)))
    return max(found)[1] if found else None


def lane_status(route):
    """`route.py status --json` lanes (name -> {out, out_until, ...}); {} when it cannot be read."""
    try:
        r = subprocess.run([sys.executable, route, "status", "--json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, env=procs.child_env())
        j = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    lanes = j.get("lanes") if isinstance(j, dict) else None
    return lanes if isinstance(lanes, dict) else {}


def contract(route):
    """delegate's worker-run handshake (`route.py contract --json`): the answer when it speaks v2, else None."""
    try:
        r = subprocess.run([sys.executable, route, "contract", "--json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, env=procs.child_env())
        j = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return j if isinstance(j, dict) and j.get("worker_run") == 2 else None


def access(wanted):
    """The flag that gives a step the host, when the task was granted it (worker-run v2: every step takes `--host`)."""
    return "--host" if wanted else ""
