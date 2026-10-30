"""landed/<bead>.json: the one record that a bead's work reached its base. The land writes it once, at the push, with the sha it read
back from the remote ref; `tl lost`, `tl prune` and the loop read it, and each checks that the sha is an ancestor of the base they
mean (a record is a claim until git confirms it). Subject text, committer time and a trace outcome decide nothing for a bead that
has a record."""
from pathlib import Path
from typing import ClassVar

from taskloop.contracts import paths
from taskloop.contracts.ids import BeadId
from taskloop.contracts.stores import JsonStore
from taskloop.contracts.wire import Rec


class Landed(Rec):
    V: ClassVar[int] = 1
    bead: BeadId
    sha: str  # the base ref's tip as `git ls-remote` showed it right after the push
    base: str  # the base ref the land pushed to (origin/main)
    t: float  # wall clock of the push; a rebase never rewrites it


class LandedStore:
    """The one reader and the one writer (atomic replace) of landed/<bead>.json. A newer land of a reopened bead replaces the older."""

    def __init__(self, cfg: paths.ConfigDir | Path | str) -> None:
        self.cfg = cfg if isinstance(cfg, paths.ConfigDir) else paths.ConfigDir(cfg)

    def get(self, bead: BeadId) -> Landed | None:
        return JsonStore(self.cfg.landed(bead), Landed).read()

    def put(self, rec: Landed) -> None:
        JsonStore(self.cfg.landed(rec.bead), Landed).write(rec)
