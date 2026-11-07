"""Log capabilities specific to landing a stack."""
from collections.abc import MutableMapping
from typing import Protocol

from tlkernel.stagefacts import RunLogPort


class StackLog(RunLogPort, Protocol):
    """A stack can name the bead stamped on subsequent log rows."""

    @property
    def stamp(self) -> MutableMapping[str, str]: ...
