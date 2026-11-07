"""What a machine supplies to the slot code: bd, the repo root, the host name, the take lock, events, tickets, the clock and the effects.
A frozen dataclass of callables over kernel ports, bound once by the composition root (app/wire/slots.py)."""
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tlkernel.bead import Bead
from tlkernel.beadsport import Beads
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir
from tlkernel.storeapi import Tickets

from tlslots.effects import Effects


@dataclass(frozen=True)
class SlotsHost:
    bd: Callable[[str, str], Beads]  # (actor, repo)
    peek: Callable[[Beads, BeadId], Bead | None]
    repo_root: Callable[[], str]
    hostname: Callable[[], str]
    os_lock: Callable[[Path | str, str], AbstractContextManager[Any]]
    event: Callable[..., Any]
    tickets: Callable[[ConfigDir], Tickets]
    now: Callable[[], float]
    fx: Effects
