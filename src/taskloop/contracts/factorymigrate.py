"""Application-owned upgrade steps for authoritative factory.db schemas."""

import sqlite3

from sqlite_store import Step


def bead_body(con: sqlite3.Connection) -> None:
    """Keep v2 rows while adding the dashboard's complete bead projection."""
    con.execute("ALTER TABLE bead ADD COLUMN body TEXT NOT NULL DEFAULT '{}'")

def checkpoint_table(con: sqlite3.Connection) -> None:
    """v4: the per-bead checkpoint, one revisioned row (STORE slice 3)."""
    con.execute("CREATE TABLE checkpoint (bead TEXT PRIMARY KEY, t REAL NOT NULL, rev INTEGER NOT NULL DEFAULT 0, body TEXT NOT NULL)")


def timed_table(con: sqlite3.Connection) -> None:
    """v5: the timed things of a run (tl-sqd3.26.11)."""
    con.execute("CREATE TABLE timed (id INTEGER PRIMARY KEY, run TEXT NOT NULL, bead TEXT, kind TEXT NOT NULL, name TEXT NOT NULL, "
                "exec_s REAL NOT NULL, wait_s REAL NOT NULL, t REAL NOT NULL)")
    con.execute("CREATE INDEX timed_run ON timed(run, id)")


# Keys are the version upgraded FROM. For the next schema change, add its step
# here, increment factorydb.SCHEMA_VERSION, and update factorydb.DDL for new DBs.
# Steps use execute, never executescript or commit: the whole chain is atomic.
STEPS: dict[int, Step] = {2: bead_body, 3: checkpoint_table, 4: timed_table}
