"""Atomic, ordered user_version upgrades."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import TypeAlias

from sqlite_store.transaction import begin_immediate

Step: TypeAlias = Callable[[sqlite3.Connection], None]


class SchemaError(sqlite3.DatabaseError):
    """The database schema cannot be read or upgraded by this code."""


def upgrade(con: sqlite3.Connection, steps: dict[int, Step], current: int, target: int, name: str = "database") -> None:
    """Recheck under one writer lock, then apply steps keyed by starting version.

    Steps must use execute, never executescript, commit or rollback: the entire
    chain, its DDL and its version changes belong to this one transaction.
    """
    with begin_immediate(con):
        current = int(con.execute("PRAGMA user_version").fetchone()[0])
        if current > target:
            message = f"{name} is schema v{current}, this code knows v{target}: update it"
            raise SchemaError(message)
        for version in range(current, target):
            step = steps.get(version)
            if step is None:
                message = f"{name} missing upgrade step v{version} -> v{version + 1}"
                raise SchemaError(message)
            try:
                step(con)
                con.execute(f"PRAGMA user_version={version + 1}")
            except Exception as error:
                message = f"{name} upgrade step v{version} -> v{version + 1} failed: {error}"
                raise SchemaError(message) from error
