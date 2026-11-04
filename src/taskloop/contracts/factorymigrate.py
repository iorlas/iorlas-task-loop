"""Atomic, ordered upgrades for authoritative factory.db schemas."""

import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager

Step = Callable[[sqlite3.Connection], None]

# Keys are the version upgraded FROM. For the next schema change, add its step
# here, increment factorydb.SCHEMA_VERSION, and update factorydb.DDL for new DBs.
# Steps use execute, never executescript or commit: the whole chain is atomic.
STEPS: dict[int, Step] = {}


class SchemaError(sqlite3.DatabaseError):
    """A schema version cannot be opened or upgraded by this task-loop."""


@contextmanager
def begin_immediate(con: sqlite3.Connection) -> Generator[None]:
    """Commit one writer transaction, rolling back on any failure."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
        con.commit()
    except BaseException:
        con.rollback()
        raise


def upgrade(con: sqlite3.Connection, steps: dict[int, Step], current: int, target: int) -> None:
    """Upgrade in place under one writer lock; another opener may have won it."""
    with begin_immediate(con):
        current = con.execute("PRAGMA user_version").fetchone()[0]
        if current > target:
            raise SchemaError(f"factory.db is schema v{current}, this task-loop knows v{target}: update task-loop")
        for version in range(current, target):
            step = steps.get(version)
            if step is None:
                raise SchemaError(f"factory.db missing upgrade step v{version} -> v{version + 1}")
            try:
                step(con)
                con.execute(f"PRAGMA user_version={version + 1}")
            except Exception as error:
                raise SchemaError(f"factory.db upgrade step v{version} -> v{version + 1} failed: {error}") from error
