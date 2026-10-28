"""The engine lock: a running engine in a worktree. run-task writes <worktree>/.task/engine.lock {pid, start, bead, slot, slot_bead, by,
route: [pid, start], workers: [[pid, start]]}; the loop writes one (by "loop") from its slot take until its run-task replaces it. The loop,
`tl slot reset|release` and another run-task keep off a worktree whose lock names a live process, whatever the slot bead says. A process is
the one in the lock only while its start time matches (pid reuse) and it is no zombie."""
import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

from taskloop.adapters.pidcheck import proc_alive, proc_start
from taskloop.app.slots.env import stamp
from taskloop.contracts.paths import RepoDirs


def engine_lock_path(wt: str | Path) -> Path:
    return RepoDirs(wt).engine_lock()


def read_engine_lock(wt: str | Path) -> dict[str, Any]:
    try:
        lock = json.loads(engine_lock_path(wt).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return lock if isinstance(lock, dict) else {}


def write_engine_lock(wt: str | Path, data: dict[str, Any]) -> None:
    f = engine_lock_path(wt)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, f)


def drop_engine_lock(wt: str | Path, pid: int | None = None) -> None:
    """Remove the lock; with `pid`, only when that process wrote it."""
    if pid is not None and read_engine_lock(wt).get("pid") != pid:
        return
    with contextlib.suppress(OSError):
        engine_lock_path(wt).unlink()


def loop_lock(wt: str | Path, slot: str, slot_bead: str, bead: str = "") -> None:
    """The loop's lock from its slot take to its run-task's own: no hand run gets in during the slot reset. `bead`, once claimed: the
    area check sees it there."""
    write_engine_lock(wt, {"pid": os.getpid(), "start": proc_start(os.getpid()), "bead": bead, "slot": slot or "",
                           "slot_bead": slot_bead or "", "by": "loop", "started": time.time()})


def engine_busy(wt: str | Path, handoff: bool = False) -> str:
    """What runs in this worktree, with the lock's path ("engine pid N runs BEAD since T; lock P"), or "". handoff: a run-task the loop
    started takes over its parent loop's lock for the same slot bead."""
    lock = read_engine_lock(wt)
    if not lock:
        return ""
    mine = {os.getpid()}
    if handoff and lock.get("by") == "loop" and lock.get("slot_bead", "") == os.environ.get("TASK_LOOP_SLOT_BEAD", ""):
        mine.add(os.getppid())
    where = f"; lock {engine_lock_path(wt)}"
    pid = lock.get("pid")
    if pid and int(pid) not in mine and proc_alive(pid, lock.get("start") or ""):
        who = "loop" if lock.get("by") == "loop" else "engine"
        return f"{who} pid {pid} runs {lock.get('bead') or 'a slot reset'} since {stamp(float(lock.get('started') or 0))}{where}"
    left: list[str] = []
    for w in [lock.get("route"), *(lock.get("workers") or [])]:
        p, st = (w[0], w[1]) if isinstance(w, (list, tuple)) else (w, "")
        if p and int(p) not in mine and proc_alive(p, st):
            left.append(str(p))
    if left:
        return f"worker pid {','.join(left)} of {lock.get('bead') or '?'} outlived its engine{where}"
    return ""
