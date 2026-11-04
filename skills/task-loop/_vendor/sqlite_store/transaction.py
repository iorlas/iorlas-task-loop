"""Short writer transactions and connection-local change observations."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Generator


@contextmanager
def begin_immediate(con: sqlite3.Connection) -> Generator[None]:
    """Commit on success; roll back on any BaseException, including commit failure."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
        con.commit()
    except BaseException:
        con.rollback()
        raise


def change_counter(con: sqlite3.Connection) -> int:
    """Compare successive data_version values on this connection only.

    Only another connection's commit changes the counter; counters from
    different connections cannot be compared.
    """
    return int(con.execute("PRAGMA data_version").fetchone()[0])
