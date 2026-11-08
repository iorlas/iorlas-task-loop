"""Which beads run now, and the area lock a run-task takes before the engine lock (the loop's and run-task's shared view)."""
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tlareas.host import AreasHost
from tlkernel.beadsport import Beads
from tlkernel.config import EngineConfig
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId, is_bead_id
from tlkernel.lockenums import LockWhat
from tlslots import engine_lock

from taskloop.adapters import beadtools
from taskloop.adapters.locks import hold_path
from taskloop.app.track import console
from taskloop.app.wire import slotfx
from taskloop.app.wire import slots as wslots


def running(repo: str, git: Git, who: Identity, store: Beads | None = None) -> dict[BeadId, str]:
    """{bead: where} of the beads running now: a slot bead held for one (held_bead), or a live engine lock naming one, in a slot
    or any worktree of the repo."""
    out: dict[BeadId, str] = {}
    slots = wslots.slot_beads(repo, who, store)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for b in slots:
        bid = b.metadata.get("held_bead")
        if is_bead_id(bid) and b.status == "in_progress" and not (b.lease_expires_at and b.lease_expires_at < stamp):
            out[bid] = b.title.split()[-1]
    for wt in wslots.worktrees(repo, git, who, slots):
        lock = engine_lock.peek_engine_lock(who.config, wt)
        if lock is not None and is_bead_id(lock.bead) and engine_lock.live(lock, fx=slotfx.FX):
            out.setdefault(lock.bead, lock.slot or Path(wt).name)
    return out


def area_lock(repo: Any, who: Identity) -> Any:
    record = who.config.lock_record(LockWhat.AREA.value, wslots.repo_key(repo))
    return hold_path(record, f"pid {os.getpid()}", what=LockWhat.AREA)


def areas_host(repo: str, cfg: EngineConfig, git: Git, who: Identity, store: Beads | None = None,
               say: Callable[[str], None] = console.say) -> AreasHost:
    """Bind admission to one store and the shared occupancy and area lock."""
    store = store if store is not None else beadtools.bd_store(who.actor, repo)
    return AreasHost(store, lambda: running(repo, git, who, store), lambda: area_lock(repo, who), say,
                     cfg.areas, cfg.area_label_prefix)
