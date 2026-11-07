"""Network pauses and re-exec notes as `wait` rows in factory.db: one open row per (kind, bead) with the record in `facts`.
A deleted row keeps its place as evidence with `cleared` set."""
import json
import sqlite3
import time
from collections.abc import Callable

from tlkernel import wire
from tlkernel.looprows import LoopRows
from tlkernel.paths import ConfigDir
from tlkernel.wire import Rec

NET_PAUSE, REEXEC = "net_pause", "reexec"


class WaitDoc[T: Rec]:
    """The get / write / delete of one bead's record of `kind`, as the file store had."""

    def __init__(self, cfg: ConfigDir, kind: str, bead: str, tp: type[T]) -> None:
        self.rows, self.kind, self.bead, self.tp = LoopRows(cfg, ""), kind, bead, tp

    def get(self) -> T | None:
        found = self.rows.select("SELECT facts FROM wait WHERE kind=? AND wake_on=? AND cleared IS NULL ORDER BY id DESC LIMIT 1",
                                 (self.kind, self.bead))
        if found:
            return self.decode(found[0][0])
        return None

    def write(self, rec: T) -> None:
        with self.rows.transaction() as con:
            self._write(con, rec)

    def change(self, fn: Callable[[T | None], T]) -> T:
        """Read, `fn`, write: all in one write transaction, so two writers of the record never lose each other's change."""
        with self.rows.transaction() as con:
            found = con.execute("SELECT facts FROM wait WHERE kind=? AND wake_on=? AND cleared IS NULL ORDER BY id DESC LIMIT 1",
                                (self.kind, self.bead)).fetchone()
            rec = fn(self.decode(found[0]) if found else None)
            self._write(con, rec)
        return rec

    def _write(self, con: sqlite3.Connection, rec: T) -> None:
        facts = json.dumps(wire.dump(rec), ensure_ascii=False)
        wake = float(getattr(rec, "retry_at", 0.0) or 0.0) or None
        run = str(getattr(rec, "run", "")) or None
        done = con.execute("UPDATE wait SET facts=?, wake_at=?, run=? WHERE kind=? AND wake_on=? AND cleared IS NULL",
                           (facts, wake, run, self.kind, self.bead)).rowcount
        if not done:
            con.execute("INSERT INTO wait (repo, run, kind, wake_at, wake_on, facts, since) VALUES ('', ?, ?, ?, ?, ?, ?)",
                        (run, self.kind, wake, self.bead, facts, time.time()))

    def delete(self) -> None:
        with self.rows.transaction() as con:
            con.execute("UPDATE wait SET cleared=? WHERE kind=? AND wake_on=? AND cleared IS NULL", (time.time(), self.kind, self.bead))

    def decode(self, text: str) -> T | None:
        try:
            return wire.load(self.tp, json.loads(text))
        except (ValueError, TypeError):
            return None


def open_records[T: Rec](cfg: ConfigDir, kind: str, tp: type[T]) -> dict[str, T]:
    """bead -> its open record of `kind` (read-only and quiet, as the dashboard reads)."""
    rows = LoopRows(cfg, "", quiet=True)
    out: dict[str, T] = {}
    for bead, facts in rows.select("SELECT wake_on, facts FROM wait WHERE kind=? AND cleared IS NULL ORDER BY id", (kind,)):
        rec = WaitDoc(cfg, kind, bead, tp).decode(facts)
        if rec is not None:
            out[bead] = rec
    return out
