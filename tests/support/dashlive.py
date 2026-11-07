"""Engine and worker log fixtures for dashboard live-feed tests."""
import json
import os

from support.logs import typed
from support.runs import manifest

BEAD, STAMP = "tl-live.1", "20261026-100000"
T = 1793000000.0


def put(path, rows, mode="a"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


def make_run(root):
    """An engine log with a command and a write step, and the live file of its write call."""
    b = manifest(os.path.join(root, "task-loop"), f"{BEAD}-{STAMP}", BEAD, T)
    log = str(b.log)
    put(log, [typed("run_start", T, run_id=f"{BEAD}-{STAMP}", bead=BEAD, worktree=""),
              typed("cmd_start", T + 1, id="m1", text="git fetch -q origin"),
              typed("cmd_end", T + 3, id="m1", exit=0),
              typed("step_start", T + 4, id="n1", text="write: x", step="write"),
              typed("call_start", T + 5, id="c1", n=1, step="write", node="n1", role="worker")])
    lf = os.path.join(b.live, "01-write.jsonl")
    put(
        lf,
        [
            {"t": T + 6, "k": "start", "harness": "codex", "lane": "CODEX", "model": "gpt-x", "effort": "high", "role": "worker", "pid": 1},
            {"t": T + 6.5, "k": "msg", "text": "between the start and the command"},
            {"t": T + 7, "k": "cmd_start", "id": "1", "text": "pytest -q", "cwd": "/w"},
        ],
    )
    return b, lf

