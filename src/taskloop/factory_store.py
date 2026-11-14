"""Read-only compatibility gate for the factory's persisted execution state."""

import sqlite3
from contextlib import closing
from functools import cache
from pathlib import Path

from sqlite_store import SchemaError, Store

from taskloop.factory_schema import SCHEMA, refusal


def _tables(con: sqlite3.Connection) -> frozenset[str]:
    return frozenset(row[0] for row in con.execute("SELECT name FROM main.sqlite_schema WHERE type='table'"))


@cache
def _required_tables() -> frozenset[str]:
    with closing(sqlite3.connect(":memory:")) as con:
        con.executescript(SCHEMA.ddl)
        return _tables(con)


def validate_tables(con: sqlite3.Connection) -> None:
    """Reject incomplete same-version state without writing to or repairing it."""
    missing = _required_tables() - _tables(con)
    if missing:
        raise SchemaError(f"missing required tables: {', '.join(sorted(missing))}")


def open_ro(database: Path) -> sqlite3.Connection | None:
    """Open compatible existing state, explain incompatibility, or return None for unavailable storage."""
    con = None
    try:
        con = Store(SCHEMA).open_ro(database)
        if con is not None:
            validate_tables(con)
    except (sqlite3.Error, OSError, ValueError, RuntimeError) as error:
        if con is not None:
            con.close()
        if isinstance(error, SchemaError):
            raise SchemaError(refusal(error, database)) from error
        return None
    else:
        return con
