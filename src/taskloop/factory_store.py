"""Read-only compatibility gate for the factory's persisted execution state."""

import sqlite3
from contextlib import closing
from functools import cache
from pathlib import Path

from sqlite_store import SchemaError, Store

from taskloop.factory_schema import SCHEMA


def current(con: sqlite3.Connection) -> bool:
    """The connection's database is exactly this code's schema version."""
    return con.execute("PRAGMA user_version").fetchone() == (SCHEMA.version,)


def refusal(error: SchemaError, path: Path) -> str:
    """Explain an incompatible restart without changing the database or offering unsafe upgrade recovery."""
    found = _recorded(path)
    diagnosis = (f"its recorded schema version could not be read ({error})" if found is None else
                 f"it records schema version {found}" + (" (no schema version recorded)" if found == 0 else ""))
    if found == SCHEMA.version:
        diagnosis += f"; the database is incompatible: {' '.join(str(error).splitlines())}"
    return (f"Restart refused: factory.db at {path.resolve()}: {diagnosis}; this runtime expects schema version {SCHEMA.version}. "
            "The database has been preserved. Resume with matching code to keep unfinished work. For an incompatible "
            "upgrade, first stop admitting work and let running attempts and their entry processes finish under the "
            "matching runtime. Draining belongs before the upgrade; this incompatible runtime cannot safely perform it. "
            "Stopping rounds alone does not confirm that entries or agents have stopped. After confirming they have "
            "stopped, the owner deliberately discards the old factory database before initializing the new runtime. "
            "Discard loses local execution progress and session references.")


def _recorded(path: Path) -> int | None:
    """The schema version the file records, read-only (only to word a refusal); None when it cannot be read."""
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError, ValueError):
        return None
    try:
        return int(con.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        con.close()


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
