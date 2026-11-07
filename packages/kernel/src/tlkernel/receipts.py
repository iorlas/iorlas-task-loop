"""Owner-command receipts in factory.db's receipt_doc table: what the dashboard answered to one idempotency key, kept so a retry of the
same click (a lost reply, a reload, a second tab) gets that answer back instead of acting twice."""

import json
import sqlite3
from typing import Final

from tlkernel.docrows import RECEIPT_DOCS

PREFIX: Final = "receipt."
KEEP_S: Final = 7 * 24 * 3600.0


def get(con: sqlite3.Connection, key: str) -> dict[str, object] | None:
    found = con.execute(f"SELECT v FROM {RECEIPT_DOCS} WHERE k=?", (PREFIX + key,)).fetchone()
    return json.loads(found[0]) if found else None


def put(con: sqlite3.Connection, key: str, receipt: dict[str, object], now: float) -> None:
    """Keep the first receipt of a key; receipts older than a week go."""
    con.execute(f"DELETE FROM {RECEIPT_DOCS} WHERE k LIKE ? AND t<?", (PREFIX + "%", now - KEEP_S))
    con.execute(f"INSERT OR IGNORE INTO {RECEIPT_DOCS}(k,v,t) VALUES (?,?,?)", (PREFIX + key, json.dumps(receipt, sort_keys=True), now))
