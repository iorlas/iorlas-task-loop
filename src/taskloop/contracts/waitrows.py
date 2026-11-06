"""Parks, network pauses and re-exec notes as `wait` rows in factory.db: one open row per (kind, bead) with the record in `facts`.
`wake_at` is the epoch a transient park wakes (0/NULL: waits for the owner). A deleted row keeps its place as evidence with `cleared`
set."""
import json
import time

from taskloop.contracts import wire
from taskloop.contracts.looprows import LoopRows
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.wire import Rec

PARK, NET_PAUSE, REEXEC = "park", "net_pause", "reexec"


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
        facts = json.dumps(wire.dump(rec), ensure_ascii=False)
        wake = float(getattr(rec, "retry_at", 0.0) or 0.0) or None
        run = str(getattr(rec, "run", "")) or None
        now = time.time()
        with self.rows.transaction() as con:
            done = con.execute("UPDATE wait SET facts=?, wake_at=?, run=? WHERE kind=? AND wake_on=? AND cleared IS NULL",
                               (facts, wake, run, self.kind, self.bead)).rowcount
            if not done:
                con.execute("INSERT INTO wait (repo, run, kind, wake_at, wake_on, facts, since) VALUES ('', ?, ?, ?, ?, ?, ?)",
                            (run, self.kind, wake, self.bead, facts, now))

    def delete(self) -> None:
        with self.rows.transaction() as con:
            con.execute("UPDATE wait SET cleared=? WHERE kind=? AND wake_on=? AND cleared IS NULL", (time.time(), self.kind, self.bead))

    def decode(self, text: str) -> T | None:
        try:
            body = json.loads(text)
            if isinstance(body, dict):  # forward-readable: a key this tl does not know (a newer writer's) is read past
                body = {k: v for k, v in body.items() if k in wire.keys(self.tp)}
            return wire.load(self.tp, body)
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
