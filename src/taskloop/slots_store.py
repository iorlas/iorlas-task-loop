"""Persistence for slot adoption and observation; connections are borrowed, never closed here."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import cached_property
from pathlib import Path

from sqlite_store import begin_immediate

from taskloop.factory_schema import SLOT, current, marks


class SlotsUnavailable(Exception):
    """Slot persistence could not be read or written."""


class SlotsStore:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection | None],
        begin: Callable[[sqlite3.Connection], AbstractContextManager[None]] = begin_immediate,
    ) -> None:
        self.connect = connect
        self.begin = begin

    @cached_property
    def _connection(self) -> sqlite3.Connection:
        con = self.connect()
        if con is None:
            raise SlotsUnavailable("Slot store unavailable")
        return con

    def require_current(self) -> None:
        try:
            if not current(self._connection):
                raise SlotsUnavailable("Slot store incompatible")
        except sqlite3.Error as error:
            raise SlotsUnavailable("Slot schema unavailable") from error

    def adopted(self, repo_id: str) -> dict[str, Path]:
        try:
            rows: list[tuple[str, str]] = self._connection.execute(
                "SELECT name,path FROM slot WHERE repo_id=?", (repo_id,)
            ).fetchall()
        except sqlite3.Error as error:
            raise SlotsUnavailable("Slot rows unavailable") from error
        return {name: Path(path) for name, path in rows}

    def paths(self) -> tuple[tuple[str, Path], ...]:
        try:
            rows: list[tuple[str, str]] = self._connection.execute("SELECT repo_id,path FROM slot").fetchall()
        except sqlite3.Error as error:
            raise SlotsUnavailable("Slot paths unavailable") from error
        return tuple((repo_id, Path(path)) for repo_id, path in rows)

    def insert(self, repo_id: str, paths: dict[str, Path]) -> dict[str, Path]:
        try:
            con = self._connection
            with self.begin(con):
                for name, path in paths.items():
                    con.execute(f"INSERT OR IGNORE INTO slot ({SLOT}) VALUES ({marks(SLOT)})", (repo_id, name, str(path)))
                return self.adopted(repo_id)
        except sqlite3.Error as error:
            raise SlotsUnavailable("Slot adoption unavailable") from error

    def reservations(self, repo_id: str) -> dict[str, str]:
        try:
            rows: list[tuple[str, str]] = self._connection.execute(
                "SELECT slot,attempt_id FROM reservation WHERE repo_id=?", (repo_id,)
            ).fetchall()
        except sqlite3.Error as error:
            raise SlotsUnavailable("Slot reservations unavailable") from error
        return dict(rows)

    def reservation(self, repo_id: str, name: str) -> str | None:
        try:
            row: tuple[object, ...] | None = self._connection.execute(
                "SELECT attempt_id FROM reservation WHERE repo_id=? AND slot=?", (repo_id, name)
            ).fetchone()
        except sqlite3.Error as error:
            raise SlotsUnavailable("Slot reservation unavailable") from error
        return None if row is None else str(row[0])
