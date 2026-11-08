"""Effects and configuration supplied by the shell to atomic area admission."""
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass

from tlkernel.beadsport import Beads
from tlkernel.ids import BeadId


@dataclass(frozen=True)
class AreasHost:
    store: Beads
    running: Callable[[], dict[BeadId, str]]
    area_lock: Callable[[], AbstractContextManager[object]]
    say: Callable[[str], None]
    areas: Mapping[str, Sequence[str] | None]
    area_label_prefix: str
