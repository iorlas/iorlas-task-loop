"""parks/<bead>.json: what the loop knows of a bead that runs ended on a question. The hash is the bead's own text (title, description,
acceptance) when the last such run ended, `runs` how many of them ended on that text. The loop will not take the bead again while the
text is the same, and nobody takes it a third time: the owner changes the bead, or the record goes."""
from pathlib import Path
from typing import ClassVar

from taskloop.contracts import paths
from taskloop.contracts.ids import BeadId
from taskloop.contracts.stores import JsonStore
from taskloop.contracts.wire import Rec


class Park(Rec):
    V: ClassVar[int] = 1
    bead: BeadId
    hash: str  # sha1 of title, description and acceptance criteria at the end of the last such run
    runs: int  # runs that ended on a question with this hash
    run: str  # the last of them (a close that is applied twice counts once)
    t: float


class ParkStore:
    """The one reader and the one writer (atomic replace) of parks/<bead>.json."""

    def __init__(self, cfg: paths.ConfigDir | Path | str) -> None:
        self.cfg = cfg if isinstance(cfg, paths.ConfigDir) else paths.ConfigDir(cfg)

    def get(self, bead: BeadId) -> Park | None:
        return JsonStore(self.cfg.park(bead), Park).get()

    def put(self, rec: Park) -> None:
        JsonStore(self.cfg.park(rec.bead), Park).write(rec)

    def drop(self, bead: BeadId) -> None:
        JsonStore(self.cfg.park(bead), Park).delete()
