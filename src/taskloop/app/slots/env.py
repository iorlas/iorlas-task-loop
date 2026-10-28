"""What the slot code is handed: the repo, its bd, its git, its ticket line and the few effects it may cause. The composition
root (tl.py) builds one; a test builds one on fakes. Nothing here reads the process environment."""
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taskloop.contracts import paths
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import SlotsConfig
from taskloop.contracts.ports import BdFailure, Beads
from taskloop.contracts.slots import SlotGit
from taskloop.stores.api import Tickets

DEFAULT_PRIO = 2
TICKET_POLL = (1, 5)  # a waiter's seconds between looks: the first, and the most


@dataclass
class SlotEnv:
    repo: str
    repo_key: str
    cfg: SlotsConfig
    store: Beads
    git: SlotGit
    tickets: Tickets
    cfgdir: paths.ConfigDir
    actor: str
    host: str
    take_lock: Callable[[], AbstractContextManager[Any]]  # every claim of this repo's slots, one at a time
    busy: Callable[[str], str]  # what runs in a worktree ("" when nothing does)
    drop_engine_lock: Callable[[str], None]
    event: Callable[..., Any]
    run_setup: Callable[[str, str], int]  # (command, worktree) -> exit code
    exclude_local: Callable[[str], None]
    say: Callable[[str], None] = print
    warn: Callable[[str], None] = print
    pid: int = 0
    now: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    extra: dict[str, str] = field(default_factory=dict)

    def dir_of(self, name: str) -> str:
        root = self.cfg.dir
        return str(Path(root if Path(root).is_absolute() else Path(self.repo) / root) / name)


def stamp(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def peek(store: Beads, bead_id: str) -> Bead | None:
    """The bead, None when it is not there or bd could not be asked."""
    try:
        return store.show(bead_id)
    except BdFailure:
        return None


def attempt(call: Callable[..., Any], *args: Any) -> bool:
    """A bd write whose refusal changes nothing: True when it worked."""
    try:
        call(*args)
        return True
    except BdFailure:
        return False
