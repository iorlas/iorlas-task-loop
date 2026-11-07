"""Parks (`wait` rows of kind park; parks/<bead>.json before): question counts and durable pause wakes. `runs` counts questions on
the same bead text; `attempts` counts pauses by producer:reason across runs. Transient
pauses carry an epoch retry_at; needs_owner pauses wake on owner input."""
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import msgspec

from taskloop.contracts import paths
from taskloop.contracts.delegate import Permanence
from taskloop.contracts.ids import BeadId
from taskloop.contracts.waitrows import PARK, WaitDoc
from taskloop.contracts.wire import Rec


class Park(Rec):
    V: ClassVar[int] = 1
    bead: BeadId
    hash: str  # sha1 of title, description and acceptance criteria at the end of the last such run
    runs: int  # runs that ended on a question with this hash
    run: str  # the last of them (a close that is applied twice counts once)
    t: float
    reason: str = ""
    permanence: Permanence = "needs_owner"
    retry_at: float = 0.0
    attempts: dict[str, int] = msgspec.field(default_factory=dict)
    fingerprint: str = ""


class ParkStore:
    """The one reader and the one writer of a bead's park."""

    def __init__(self, cfg: paths.ConfigDir | Path | str) -> None:
        self.cfg = cfg if isinstance(cfg, paths.ConfigDir) else paths.ConfigDir(cfg)

    def doc(self, bead: BeadId) -> WaitDoc[Park]:
        return WaitDoc(self.cfg, PARK, bead, Park)

    def get(self, bead: BeadId) -> Park | None:
        return self.doc(bead).get()

    def retry_at(self, bead: BeadId, run: str) -> float:
        """The durable wake for this run; an absent or older park has no timer."""
        rec = self.get(bead)
        return rec.retry_at if rec is not None and rec.run == run else 0.0

    def change(self, bead: BeadId, fn: Callable[[Park | None], Park]) -> Park:
        """The park after `fn` saw the stored one (None: no park), read and written in one transaction."""
        return self.doc(bead).change(fn)

    def put(self, rec: Park) -> None:
        self.doc(rec.bead).write(rec)

    def drop(self, bead: BeadId) -> None:
        self.doc(bead).delete()
