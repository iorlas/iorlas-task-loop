"""The engine lock: a running engine in a worktree. run-task writes the worktree's lock row in factory.db, never a file in the worktree
a worker can write (contracts/locks.py EngineLock: pid, start,
bead, slot, slot_bead, by); the loop writes one (by "loop") from its slot take until its run-task replaces it. The loop,
`tl slot reset|release` and another run-task keep off a worktree whose lock names a live process, whatever the slot bead says. A process is
the one in the lock only while its start time matches (pid reuse) and it is no zombie. The record is a `lease` row (contracts/lockrows.py;
an older tl's file is read until the next write); the check and the write of a take happen under `hold_path` on
ConfigDir.engine_take, so two runs starting at once cannot both win."""
import contextlib
import os
import time
from pathlib import Path

from taskloop.adapters.agent import running_for
from taskloop.adapters.locks import hold_path
from taskloop.adapters.pidcheck import proc_alive, proc_start
from taskloop.app.slots.env import stamp
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ids import loop_key
from taskloop.contracts.lockrows import EngineLockRows
from taskloop.contracts.locks import EngineLock as Lock
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import Reexec
from taskloop.contracts.wire import Refused


def _store(cfg: ConfigDir, wt: str | Path) -> EngineLockRows:
    return EngineLockRows(cfg, wt)


def read_engine_lock(cfg: ConfigDir, wt: str | Path) -> Lock | None:
    """The lock record; None when there is none. A lock file that is torn or of another version is Refused (naming it): it is never
    read as no lock, which would let a second engine into the worktree."""
    return _store(cfg, wt).need()


def peek_engine_lock(cfg: ConfigDir, wt: str | Path) -> Lock | None:
    """The lock record for a display or a sweep: a file that cannot be read shows as none (engine_busy still refuses on it)."""
    return _store(cfg, wt).get()


def write_engine_lock(cfg: ConfigDir, wt: str | Path, rec: Lock) -> None:
    _store(cfg, wt).write(rec)


def drop_engine_lock(cfg: ConfigDir, wt: str | Path, pid: int | None = None) -> None:
    """Remove the lock; with `pid`, only when that process wrote it."""
    if pid is not None:
        held = peek_engine_lock(cfg, wt)
        if held is None or held.pid != pid:
            return
    _store(cfg, wt).delete()


def lock_pid(cfg: ConfigDir, wt: str | Path) -> int | None:
    """The pid the worktree's engine lock names (0: a worker outlived its engine), None when there is none."""
    held = peek_engine_lock(cfg, wt)
    return held.pid if held else None


def loop_lock(cfg: ConfigDir, wt: str | Path, slot: str, slot_bead: str, bead: str = "") -> None:
    """The loop's lock from its slot take to its run-task's own: no hand run gets in during the slot reset. `bead`, once claimed: the
    area check sees it there."""
    with hold_path(cfg.engine_take(wt), "loop", what=LockWhat.WORKTREE):
        write_engine_lock(cfg, wt, Lock(pid=os.getpid(), start=proc_start(os.getpid()), bead=bead, slot=slot or "",
                                        slot_bead=slot_bead or "", by="loop", started=time.time()))


def live(lock: Lock | None) -> bool:
    """The lock names a process that runs now (the engine or loop itself, not its leftovers)."""
    return lock is not None and bool(lock.pid) and proc_alive(lock.pid, lock.start)


def engine_busy(cfg: ConfigDir, wt: str | Path, handoff: Env | None = None) -> str:
    """What runs in this worktree, with the lock's path ("engine pid N runs BEAD since T; lock P"), or "".
    handoff: the Env of a run-task takes over its loop's lock for the same slot bead, or its reexec predecessor's for the same bead.
    The loop names itself in TASK_LOOP_LOOP_PID: run-task's parent is `uv run --script`, not the loop: the parent pid never matches."""
    try:
        lock = read_engine_lock(cfg, wt)
    except Refused as err:
        return f"{err}"  # fail closed: a lock nobody can read still holds the worktree
    if lock is None:
        return ""
    mine = {os.getpid()}
    if handoff is not None and lock.by == "loop" and lock.slot_bead == handoff.get(EnvVar.TASK_LOOP_SLOT_BEAD):
        with contextlib.suppress(ValueError):
            mine.add(int(handoff.get(EnvVar.TASK_LOOP_LOOP_PID)))
    if handoff is not None:
        handed = Reexec.parse(handoff.get(EnvVar.TL_REEXEC))
        if handed is not None and handed.pid == lock.pid and handed.bead == lock.bead:
            mine.add(handed.pid)  # exec leaves uv at this pid; its new Python child takes the lock next
    where = f"; lock engine:{loop_key(wt)} in {cfg.factory_db()}"
    if lock.pid and lock.pid not in mine and proc_alive(lock.pid, lock.start):
        who = "loop" if lock.by == "loop" else "engine"
        return f"{who} pid {lock.pid} runs {lock.bead or 'a slot reset'} since {stamp(lock.started)}{where}"
    left = running_for(lock.bead)
    if left:
        return f"worker run {','.join(left)} of {lock.bead or '?'} outlived its engine{where}"
    return ""


class EngineLock:
    """The worktree's engine lock while run-task runs there (see engine_busy). A worker that outlived its stop keeps the lock (pid 0)
    until it is gone."""

    def __init__(self, cfg: ConfigDir, wt: str | Path, bead: str, slot: str = "", env: Env | None = None) -> None:
        self.env = env or Env()
        self.cfg, self.wt = cfg, wt
        self.rec = Lock(pid=os.getpid(), start=proc_start(os.getpid()), bead=bead, slot=slot or "",
                        slot_bead=self.env.get(EnvVar.TASK_LOOP_SLOT_BEAD), by="run-task", started=time.time())

    def take(self) -> str:
        """"" when this run holds the worktree now, else what holds it. Loop and reexec handoffs take over their predecessor's lock."""
        with hold_path(self.cfg.engine_take(self.wt), f"pid {os.getpid()}", what=LockWhat.WORKTREE):
            busy = engine_busy(self.cfg, self.wt, handoff=self.env)
            if busy:
                return busy
            self.write()  # a dead run's lock, or a handed-over lock (engine_busy said so), is replaced
            return ""

    def write(self) -> None:
        write_engine_lock(self.cfg, self.wt, self.rec)

    def note(self, **kw: object) -> None:
        self.rec = self.rec.replace(**kw)
        self.write()

    def release(self) -> None:
        left = running_for(self.rec.bead)
        with contextlib.suppress(OSError):
            if left:
                self.note(pid=0)
            else:
                drop_engine_lock(self.cfg, self.wt)


LOCK: EngineLock | None = None  # this process's EngineLock while run-task runs
