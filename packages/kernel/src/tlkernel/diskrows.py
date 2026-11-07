"""Free-space samples of the config volume in factory.db's disk_doc table (tl-7i9k.24.1): the loop adds one an hour,
`tl doctor --disk` fits a line over the last week. A sample is the row `disk.free.<hour>` holding the free bytes
at the time `t` of the row; a fortnight is kept."""

import sqlite3
from typing import Final

from tlkernel.docrows import DISK_DOCS

PREFIX: Final = "disk.free."
KEEP_S: Final = 14 * 24 * 3600.0
HOUR_S: Final = 3600.0


def sample(con: sqlite3.Connection, free: int, now: float) -> None:
    """Keep the first sample of an hour; samples older than KEEP_S go."""
    con.execute(f"DELETE FROM {DISK_DOCS} WHERE k LIKE ? AND t<?", (PREFIX + "%", now - KEEP_S))
    con.execute(f"INSERT OR IGNORE INTO {DISK_DOCS}(k,v,t) VALUES (?,?,?)", (f"{PREFIX}{int(now // HOUR_S)}", str(free), now))


def samples(con: sqlite3.Connection) -> list[tuple[float, int]]:
    """[(time, free bytes)], oldest first."""
    rows = con.execute(f"SELECT t, v FROM {DISK_DOCS} WHERE k LIKE ? ORDER BY t", (PREFIX + "%",)).fetchall()
    return [(float(t), int(v)) for t, v in rows]
