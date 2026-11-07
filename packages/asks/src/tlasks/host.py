"""Machine services for ask admission and parks, supplied by the shell."""
from collections.abc import Callable
from dataclasses import dataclass

from tlkernel.askport import AskReader
from tlkernel.bead import Bead
from tlkernel.beadsport import Beads
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir


@dataclass(frozen=True)
class AsksHost:
    bd: Callable[[str, str], Beads]
    peek: Callable[[Beads, BeadId], Bead | None]
    hostname: Callable[[], str]
    asks_store: Callable[[ConfigDir], AskReader]
