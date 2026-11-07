"""Owner-command receipts in factory.db's kv table: what the dashboard answered to one idempotency key, kept so a retry of the
same click (a lost reply, a reload, a second tab) gets that answer back instead of acting twice."""

import json
import sqlite3
from typing import Final

PREFIX: Final = "receipt."
KEEP_S: Final = 7 * 24 * 3600.0


def get(con: sqlite3.Connection, key: str) -> dict[str, object] | None:
    found = con.execute("SELECT v FROM kv WHERE k=?", (PREFIX + key,)).fetchone()
    return json.loads(found[0]) if found else None


def put(con: sqlite3.Connection, key: str, receipt: dict[str, object], now: float) -> None:
    """Keep the first receipt of a key; receipts older than a week go."""
    con.execute("DELETE FROM kv WHERE k LIKE ? AND t<?", (PREFIX + "%", now - KEEP_S))
    con.execute("INSERT OR IGNORE INTO kv(k,v,t) VALUES (?,?,?)", (PREFIX + key, json.dumps(receipt, sort_keys=True), now))
