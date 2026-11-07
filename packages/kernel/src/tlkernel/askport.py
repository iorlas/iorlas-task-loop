"""The current ask of a bead, read through the authoritative store."""
from typing import Protocol

from tlkernel.ask import Ask
from tlkernel.ids import BeadId


class AskReader(Protocol):
    def get(self, bead: BeadId) -> Ask | None: ...
