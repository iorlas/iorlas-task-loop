"""One vendor call in flight as an `effect` row in factory.db: key `call:<bead>`, `name` its coordinates, `state` its
phase (calling, returned, consumed) and `receipt` the record. One row per bead, replaced by the bead's next call."""
import time

from tlkernel.looprows import LoopRows
from tlkernel.paths import ConfigDir

CONSUMED = "consumed"


def key_of(bead: str) -> str:
    return f"call:{bead}"


def put(cfg: ConfigDir, bead: str, run: str, name: str, state: str, intent_at: float, receipt: str) -> None:
    now = time.time()
    with LoopRows(cfg, "").transaction() as con:
        con.execute("INSERT INTO effect (key, run, name, state, intent_at, done_at, receipt) VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET run=excluded.run, name=excluded.name, state=excluded.state, "
                    "intent_at=excluded.intent_at, done_at=excluded.done_at, receipt=excluded.receipt",
                    (key_of(bead), run, name, state, intent_at, now if state == CONSUMED else None, receipt))


def receipt(cfg: ConfigDir, bead: str) -> str | None:
    """The record text of the bead's call, None when it has no row."""
    rows = LoopRows(cfg, "").select("SELECT receipt FROM effect WHERE key=?", (key_of(bead),))
    return rows[0][0] if rows else None


def delete(cfg: ConfigDir, bead: str) -> None:
    with LoopRows(cfg, "").transaction() as con:
        con.execute("DELETE FROM effect WHERE key=?", (key_of(bead),))
