"""Run log facts stored through contracts within caller-owned transactions."""

import sqlite3


def clear_facts(con: sqlite3.Connection) -> None:
    """Clear all log folds and offsets without changing authoritative run state."""
    con.execute("UPDATE run SET facts=NULL, facts_upto=NULL")


def read_facts(con: sqlite3.Connection, run: str) -> str | None:
    """Return encoded facts, or None for an absent row or an unindexed run."""
    row = con.execute("SELECT facts FROM run WHERE run=?", (run,)).fetchone()
    return row[0] if row else None


def write_facts(con: sqlite3.Connection, run: str, encoded: str, upto: int) -> None:
    """Replace a run's log fold and offset without inserting missing runs."""
    con.execute("UPDATE run SET facts=?, facts_upto=? WHERE run=?", (encoded, upto, run))


def count_runs(con: sqlite3.Connection) -> int:
    """Count authoritative run rows, including runs without log facts."""
    return con.execute("SELECT count(*) FROM run").fetchone()[0]
