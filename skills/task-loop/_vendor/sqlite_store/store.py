"""Conservative SQLite-on-disk opens parameterized by an application's schema."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

from sqlite_store.cas import cas_update
from sqlite_store.connections import SharedConnections
from sqlite_store.filesystem import filesystem_allowed
from sqlite_store.migrate import SchemaError, upgrade
from sqlite_store.quarantine import quarantine_if_needed
from sqlite_store.transaction import begin_immediate

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlite_store.cas import SqlValue
    from sqlite_store.migrate import Step

Identity: TypeAlias = tuple[int, Path, int, int]


@dataclass(frozen=True)
class Schema:
    """Application-owned DDL and upgrades, with no triggers or embedded semicolons.

    Steps are keyed by the version upgraded FROM and must not end transactions.
    Extra checks are SQL queries returning exactly one row containing 'ok'.
    Quarantine is opt-in for obsolete derived data, never authoritative data.
    """

    version: int
    ddl: str
    steps: dict[int, Step]
    name: str = "database"
    revisioned: frozenset[str] = frozenset()
    quarantine_versions: frozenset[int] = frozenset()
    checks: tuple[str, ...] = ()


def _journal_mode(con: sqlite3.Connection, *, readonly: bool) -> str:
    # SQLite ignores busy_timeout while switching journal mode on a fresh file.
    deadline = time.monotonic() + 5.0
    while True:
        try:
            row = con.execute("PRAGMA journal_mode").fetchone()
            if not readonly and row and str(row[0]).lower() != "wal":
                row = con.execute("PRAGMA journal_mode=WAL").fetchone()
        except sqlite3.OperationalError as error:
            if "locked" not in str(error) or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
        else:
            return str(row[0]).lower() if row else ""


def _configure(con: sqlite3.Connection, *, readonly: bool) -> None:
    if _journal_mode(con, readonly=readonly) != "wal":
        message = "WAL unavailable"
        raise sqlite3.DatabaseError(message)
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")


def _validate_version(version: int, schema: Schema, *, readonly: bool) -> None:
    if version > schema.version:
        message = f"{schema.name} is schema v{version}, this code knows v{schema.version}: update it"
        raise SchemaError(message)
    if readonly and version < schema.version:
        message = f"{schema.name} is schema v{version}, this code knows v{schema.version}: the writer has not upgraded it yet"
        raise SchemaError(message)


def _schema_ready(con: sqlite3.Connection, schema: Schema, version: int, *, readonly: bool) -> bool:
    created = False
    if version == 0 and not readonly:
        with begin_immediate(con):
            version = int(con.execute("PRAGMA user_version").fetchone()[0])
            empty = con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None
            if version == 0 and empty:
                # executescript would commit first, breaking atomic creation.
                for statement in schema.ddl.split(";"):
                    if statement.strip():
                        con.execute(statement)
                con.execute(f"PRAGMA user_version={schema.version}")
                version = schema.version
                created = True
    _validate_version(version, schema, readonly=readonly)
    if version == 0 and version != schema.version:
        message = "unsupported schema version"
        raise sqlite3.DatabaseError(message)
    if version < schema.version:
        upgrade(con, schema.steps, version, schema.version, name=schema.name)
    return created


def _check_integrity(
    con: sqlite3.Connection,
    target: Path,
    schema: Schema,
    checked: set[Identity],
    *,
    created: bool,
    readonly: bool,
) -> None:
    if readonly:
        return
    stat = target.stat()
    identity = (os.getpid(), target, stat.st_dev, stat.st_ino)
    if created or identity not in checked:
        for statement in ("PRAGMA quick_check", *schema.checks):
            if con.execute(statement).fetchall() != [("ok",)]:
                message = "integrity check failed"
                raise sqlite3.DatabaseError(message)
        checked.add(identity)


def _open(
    path: str | os.PathLike[str],
    schema: Schema,
    checked: set[Identity],
    *,
    readonly: bool,
    shared: bool = False,
) -> sqlite3.Connection | None:
    con = None
    try:
        resolved = Path(path).resolve()
        if not filesystem_allowed(resolved.parent):
            return None
        address = f"{resolved.as_uri()}?mode=ro" if readonly else os.fspath(path)
        con = sqlite3.connect(address, uri=readonly, isolation_level=None, timeout=5.0, check_same_thread=not shared)
        version = int(con.execute("PRAGMA user_version").fetchone()[0])
        if readonly and version == 0 and con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None:
            # A file a writer has created but not yet initialised is not there yet, the same as a missing file.
            con.close()
            return None
        _validate_version(version, schema, readonly=readonly)
        if not readonly and version < schema.version and version in schema.quarantine_versions:
            con.close()
            quarantine_if_needed(resolved, schema.quarantine_versions)
            con = sqlite3.connect(address, isolation_level=None, timeout=5.0, check_same_thread=not shared)
            version = int(con.execute("PRAGMA user_version").fetchone()[0])
        con.execute("PRAGMA busy_timeout=5000")
        _configure(con, readonly=readonly)
        created = _schema_ready(con, schema, version, readonly=readonly)
        _check_integrity(con, resolved, schema, checked, created=created, readonly=readonly)
    except (sqlite3.Error, OSError, ValueError, RuntimeError) as error:
        if con is not None:
            with suppress(sqlite3.Error):
                con.close()
        if isinstance(error, SchemaError):
            raise
        return None
    else:
        return con


_CHECKED: set[Identity] = set()


def open_rw(path: str | os.PathLike[str], schema: Schema) -> sqlite3.Connection | None:
    """Open or create WAL storage; schema errors raise, unavailable storage is None."""
    return _open(path, schema, _CHECKED, readonly=False)


def open_ro(path: str | os.PathLike[str], schema: Schema) -> sqlite3.Connection | None:
    """Open compatible existing WAL storage read-only, without an integrity check."""
    return _open(path, schema, _CHECKED, readonly=True)


class Store:
    """One schema with its own shared writers and writable integrity-check cache."""

    def __init__(self, schema: Schema) -> None:
        self.schema = schema
        self._shared = SharedConnections()
        self._checked: set[Identity] = set()

    def _open(self, path: str | os.PathLike[str], *, readonly: bool, shared: bool = False) -> sqlite3.Connection | None:
        return _open(path, self.schema, self._checked, readonly=readonly, shared=shared)

    def open_rw(self, path: str | os.PathLike[str]) -> sqlite3.Connection | None:
        return self._open(path, readonly=False)

    def open_ro(self, path: str | os.PathLike[str]) -> sqlite3.Connection | None:
        return self._open(path, readonly=True)

    def shared_rw(self, path: str | os.PathLike[str]) -> sqlite3.Connection | None:
        """Reuse this thread's idle writer only while its PID and file identity match."""
        return self._shared.get(path, lambda target: self._open(target, readonly=False, shared=True))

    def close_shared(self) -> None:
        """Close all this process's cached writers after their operations stop."""
        self._shared.close()

    @contextmanager
    def begin_immediate(self, con: sqlite3.Connection) -> Generator[None]:
        """Commit or roll back; evict a cached writer on any SQLite DatabaseError."""
        try:
            with begin_immediate(con):
                yield
        except sqlite3.DatabaseError:
            self._shared.discard(con)
            raise

    def cas_update(self, con: sqlite3.Connection, table: str, key_col: str, key: SqlValue, rev: int, **cols: SqlValue) -> bool:
        return cas_update(con, table, key_col, key, rev, revisioned=self.schema.revisioned, **cols)
