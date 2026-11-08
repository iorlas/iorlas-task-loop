"""Which beads run now, and the area lock a run-task takes before the engine lock (the loop's and run-task's shared view)."""
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tlareas.policy import AreaLock, AreasHost, occupancy
from tlkernel.beadsport import Beads
from tlkernel.config import EngineConfig
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.lockenums import LockWhat
from tlslots import engine_lock

from taskloop.adapters import beadtools
from taskloop.adapters.locks import hold_path
from taskloop.app.track import console
from taskloop.app.wire import slotfx
from taskloop.app.wire import slots as wslots


def running(repo: str, git: Git, who: Identity, store: Beads | None = None) -> dict[BeadId, str]:
    """Bind the shared occupancy policy to this repository's slots and engine locks."""
    slots = wslots.slot_beads(repo, who, store)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return occupancy(slots, wslots.worktrees(repo, git, who, slots),
                     lambda wt: engine_lock.peek_engine_lock(who.config, wt),
                     lambda lock: engine_lock.live(lock, fx=slotfx.FX), stamp)


def area_lock(repo: Any, who: Identity) -> Any:
    record = who.config.lock_record(LockWhat.AREA.value, wslots.repo_key(repo))
    return hold_path(record, f"pid {os.getpid()}", what=LockWhat.AREA)


@dataclass(frozen=True)
class _AreasHost:
    store: Beads
    running: Callable[[], dict[BeadId, str]]
    area_lock: Callable[[], AreaLock]
    say: Callable[[str], None]
    areas: Mapping[str, Sequence[str] | None]
    area_label_prefix: str


def areas_host(repo: str, cfg: EngineConfig, git: Git, who: Identity, store: Beads | None = None,
               say: Callable[[str], None] = console.say) -> AreasHost:
    """Bind admission to one store and the shared occupancy and area lock."""
    store = store if store is not None else beadtools.bd_store(who.actor, repo)
    return _AreasHost(store, lambda: running(repo, git, who, store), lambda: area_lock(repo, who), say,
                     cfg.areas, cfg.area_label_prefix)
