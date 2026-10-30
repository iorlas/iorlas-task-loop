"""The engine lock: a running engine in a worktree. run-task writes <worktree>/.task/engine.lock (contracts/locks.py EngineLock: pid, start,
bead, slot, slot_bead, by, route, workers); the loop writes one (by "loop") from its slot take until its run-task replaces it. The loop,
`tl slot reset|release` and another run-task keep off a worktree whose lock names a live process, whatever the slot bead says. A process is
the one in the lock only while its start time matches (pid reuse) and it is no zombie. The file is a record on a JsonStore; the check and
the write of a take happen under `hold_path` on RepoDirs.engine_take, so two runs starting at once cannot both win."""
import contextlib
import os
import time
from pathlib import Path

from taskloop.adapters.locks import hold_path
from taskloop.adapters.pidcheck import proc_alive, proc_start
from taskloop.app.slots.env import stamp
from taskloop.contracts import env as penv
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.locks import EngineLock as Lock
from taskloop.contracts.paths import RepoDirs
from taskloop.contracts.stores import JsonStore


def engine_lock_path(wt: str | Path) -> Path:
    return RepoDirs(wt).engine_lock()


def _store(wt: str | Path) -> JsonStore[Lock]:
    return JsonStore(engine_lock_path(wt), Lock)


def read_engine_lock(wt: str | Path) -> Lock | None:
    """The lock record; None when there is none (or the file is not a lock of this version)."""
    return _store(wt).read()


def write_engine_lock(wt: str | Path, rec: Lock) -> None:
    _store(wt).write(rec)


def drop_engine_lock(wt: str | Path, pid: int | None = None) -> None:
    """Remove the lock; with `pid`, only when that process wrote it."""
    if pid is not None:
        held = read_engine_lock(wt)
        if held is None or held.pid != pid:
            return
    with contextlib.suppress(OSError):
        engine_lock_path(wt).unlink()


def lock_pid(wt: str | Path) -> int | None:
    """The pid the worktree's engine lock names (0: a worker outlived its engine), None when there is none."""
    held = read_engine_lock(wt)
    return held.pid if held else None


def loop_lock(wt: str | Path, slot: str, slot_bead: str, bead: str = "") -> None:
    """The loop's lock from its slot take to its run-task's own: no hand run gets in during the slot reset. `bead`, once claimed: the
    area check sees it there."""
    with hold_path(RepoDirs(wt).engine_take(), "loop", what=LockWhat.WORKTREE):
        write_engine_lock(wt, Lock(pid=os.getpid(), start=proc_start(os.getpid()), bead=bead, slot=slot or "", slot_bead=slot_bead or "",
                                   by="loop", started=time.time()))


def live(lock: Lock | None) -> bool:
    """The lock names a process that runs now (the engine or loop itself, not its leftovers)."""
    return lock is not None and bool(lock.pid) and proc_alive(lock.pid, lock.start)


def engine_busy(wt: str | Path, handoff: bool = False) -> str:
    """What runs in this worktree, with the lock's path ("engine pid N runs BEAD since T; lock P"), or "". handoff: a run-task the loop
    started takes over its loop's lock for the same slot bead. The loop names itself in TASK_LOOP_LOOP_PID: run-task's parent is
    `uv run --script`, not the loop, so the parent pid would never match."""
    lock = read_engine_lock(wt)
    if lock is None:
        return ""
    mine = {os.getpid()}
    if handoff and lock.by == "loop" and lock.slot_bead == penv.ambient(EnvVar.TASK_LOOP_SLOT_BEAD):
        with contextlib.suppress(ValueError):
            mine.add(int(penv.ambient(EnvVar.TASK_LOOP_LOOP_PID)))
    where = f"; lock {engine_lock_path(wt)}"
    if lock.pid and lock.pid not in mine and proc_alive(lock.pid, lock.start):
        who = "loop" if lock.by == "loop" else "engine"
        return f"{who} pid {lock.pid} runs {lock.bead or 'a slot reset'} since {stamp(lock.started)}{where}"
    left = [str(p) for p, st in [*([lock.route] if lock.route else []), *lock.workers] if p and p not in mine and proc_alive(p, st)]
    if left:
        return f"worker pid {','.join(left)} of {lock.bead or '?'} outlived its engine{where}"
    return ""


class EngineLock:
    """<worktree>/.task/engine.lock while run-task runs there (see engine_busy). A worker that outlived its stop keeps the lock (pid 0)
    until it is gone."""

    def __init__(self, wt: str | Path, bead: str, slot: str = "") -> None:
        self.wt = wt
        self.path = engine_lock_path(wt)
        self.rec = Lock(pid=os.getpid(), start=proc_start(os.getpid()), bead=bead, slot=slot or "",
                        slot_bead=penv.ambient(EnvVar.TASK_LOOP_SLOT_BEAD) or "", by="run-task", started=time.time())

    def take(self) -> str:
        """"" when this run holds the worktree now, else what holds it. A run the loop started takes over the loop's lock for its slot."""
        with hold_path(RepoDirs(self.wt).engine_take(), f"pid {os.getpid()}", what=LockWhat.WORKTREE):
            busy = engine_busy(self.wt, handoff=True)  # a run-task takes over only its parent loop's lock for the same slot bead
            if busy:
                return busy
            self.write()  # a dead run's lock, or the parent loop's (engine_busy said so), is replaced
            return ""

    def write(self) -> None:
        write_engine_lock(self.wt, self.rec)

    def note(self, **kw: object) -> None:
        self.rec = self.rec.replace(**kw)
        with contextlib.suppress(OSError):
            self.write()

    def release(self) -> None:
        left = [(p, st) for p, st in self.rec.workers if proc_alive(p, st)]
        with contextlib.suppress(OSError):
            if left:
                self.note(pid=0, route=None, workers=left)
            else:
                self.path.unlink()


LOCK: EngineLock | None = None  # this process's EngineLock while run-task runs
