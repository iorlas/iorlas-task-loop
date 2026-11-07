"""Parks (rows of the asks-owned `park` table): question counts and durable pause wakes. `runs` counts questions on
the same bead text; `attempts` counts pauses by producer:reason across runs. Transient
pauses carry an epoch retry_at; needs_owner pauses wake on owner input."""
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import msgspec

from tlkernel import paths
from tlkernel.delegate import Permanence
from tlkernel.docrows import RowDocs
from tlkernel.docstore import Present
from tlkernel.ids import BeadId
from tlkernel.wire import Rec


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
        self.docs = RowDocs(self.cfg, Park, table="park", key_col="bead", body_col="body")

    def get(self, bead: BeadId) -> Park | None:
        return self.docs.of(bead).get()

    def retry_at(self, bead: BeadId, run: str) -> float:
        """The durable wake for this run; an absent or older park has no timer."""
        rec = self.get(bead)
        return rec.retry_at if rec is not None and rec.run == run else 0.0

    def change(self, bead: BeadId, fn: Callable[[Park | None], Park]) -> Park:
        """The park after `fn` saw the stored one (None: no park), read and written in one transaction."""
        doc = self.docs.of(bead)
        with self.docs.rows.transaction() as con:
            found = con.execute("SELECT body FROM park WHERE bead=?", (bead,)).fetchone()
            read = doc.codec().decode(found[0]) if found else None
            rec = fn(read.rec if isinstance(read, Present) else None)
            doc.write_in(con, rec)
        return rec

    def put(self, rec: Park) -> None:
        self.docs.of(rec.bead).write(rec)

    def drop(self, bead: BeadId) -> None:
        self.docs.of(bead).delete()

    @staticmethod
    def open_parks(cfg: paths.ConfigDir) -> dict[str, Park]:
        """All decodable parks; an unavailable database reads quietly as empty for the dashboard."""
        docs = RowDocs(cfg, Park, table="park", key_col="bead", body_col="body", quiet=True)
        out: dict[str, Park] = {}
        for (bead,) in docs.rows.select("SELECT bead FROM park ORDER BY bead"):
            rec = docs.of(bead).get()
            if rec is not None:
                out[bead] = rec
        return out
