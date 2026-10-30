"""Which beads run now, and the area lock a run-task takes before the engine lock (the loop's and run-task's shared view)."""
import os
import time
from pathlib import Path
from typing import Any

from taskloop.adapters import beadtools, ident
from taskloop.adapters.locks import hold_path
from taskloop.app.loop.queue import QueueRule, area_busy_text
from taskloop.app.run import console
from taskloop.app.slots import engine_lock
from taskloop.app.wire import slots as wslots
from taskloop.contracts import paths
from taskloop.contracts.enums import LockWhat


def running(repo: Any, store: Any = None) -> dict[str, str]:
    """{bead: where} of the beads running now: a slot bead held for one (held_bead), or a live engine lock naming one, in a slot
    or any worktree of the repo."""
    out: dict[str, str] = {}
    slots = wslots.slot_beads(repo, store)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for b in slots:
        bid = b.metadata.get("held_bead")
        if bid and b.status == "in_progress" and not (b.lease_expires_at and b.lease_expires_at < stamp):
            out[bid] = b.title.split()[-1]
    for wt in wslots.worktrees(repo, slots):
        lock = engine_lock.read_engine_lock(wt)
        if lock is not None and lock.bead and engine_lock.live(lock):
            out.setdefault(lock.bead, lock.slot or Path(wt).name)
    return out


def area_lock(repo: Any) -> Any:
    record = paths.ConfigDir(ident.config_dir()).lock_record(LockWhat.AREA.value, wslots.repo_key(repo))
    return hold_path(record, f"pid {os.getpid()}", what=LockWhat.AREA)


def area_busy(repo: Any, cfg: Any, bead: Any, store: Any = None) -> tuple[str, str]:
    """(area, "area A busy: B in S") for a bead whose area runs elsewhere, (area, "") when it is free, ("", "") for none (run-task's
    check before it takes the engine lock)."""
    store = store or beadtools.bd_store(repo)
    return area_busy_text(QueueRule(store, cfg, running(repo, store), lambda b: "", console.say), bead)
