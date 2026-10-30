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
    started takes over its loop's lock for the same slot bead. The loop names itself in TASK_LOOP_LOOP_PID: run-task's parent is
    `uv run --script`, not the loop, so the parent pid would never match."""
    lock = read_engine_lock(wt)
    if not lock:
        return ""
    mine = {os.getpid()}
    if handoff and lock.get("by") == "loop" and lock.get("slot_bead", "") == os.environ.get("TASK_LOOP_SLOT_BEAD", ""):
        with contextlib.suppress(ValueError):
            mine.add(int(os.environ.get("TASK_LOOP_LOOP_PID") or ""))
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


class EngineLock:
    """<worktree>/.task/engine.lock while run-task runs there (see engine_busy). A worker that outlived its stop keeps the lock (pid 0)
    until it is gone."""

    def __init__(self, wt: str | Path, bead: str, slot: str = "") -> None:
        self.wt = wt
        self.path = engine_lock_path(wt)
        self.data: dict[str, Any] = {"pid": os.getpid(), "start": proc_start(os.getpid()), "bead": bead, "slot": slot or "",
                                     "slot_bead": os.environ.get("TASK_LOOP_SLOT_BEAD", ""), "by": "run-task", "started": time.time(),
                                     "route": None, "workers": []}

    def take(self) -> str:
        """"" when this run holds the worktree now, else what holds it. A run the loop started takes over the loop's lock for its slot."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(3):
            busy = engine_busy(self.wt, handoff=True)  # a run-task takes over only its parent loop's lock for the same slot bead
            if busy:
                return busy
            try:  # created only if absent: two runs starting at once cannot both win
                os.close(os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            except FileExistsError:
                with contextlib.suppress(OSError):  # a dead run's lock or the parent loop's (engine_busy said so)
                    if not engine_busy(self.wt, handoff=True):
                        self.path.unlink()
                continue
            self.write()
            return ""
        return "another run took the engine lock at the same time"

    def write(self) -> None:
        write_engine_lock(self.wt, self.data)

    def note(self, **kw: Any) -> None:
        self.data.update(kw)
        with contextlib.suppress(OSError):
            self.write()

    def release(self) -> None:
        left = [w for w in self.data.get("workers") or [] if proc_alive(w[0], w[1])]
        with contextlib.suppress(OSError):
            if left:
                self.data.update(pid=0, route=None, workers=left)
                self.write()
            else:
                self.path.unlink()


LOCK: EngineLock | None = None  # this process's EngineLock while run-task runs
