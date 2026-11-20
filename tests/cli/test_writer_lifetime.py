"""Public SQLite observations: shared ordinary writers retain integrity and timeout contracts."""
import sqlite3
import threading
from pathlib import Path
from typing import Literal

import pytest
from sqlite_store import Store

from taskloop.attempt_store import REGISTRATION_BUSY_MS
from taskloop.cli_composition import open_land, open_start
from taskloop.composition import open_checking
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.operations import Failed


@pytest.fixture
def observed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    statements: list[str] = []
    original = sqlite3.connect
    def connect(database: str, *, uri: bool = False,
                isolation_level: Literal["DEFERRED", "IMMEDIATE", "EXCLUSIVE"] | None = "DEFERRED", timeout: float = 5.,
                check_same_thread: bool = True) -> sqlite3.Connection:
        con = original(database, uri=uri, isolation_level=isolation_level, timeout=timeout, check_same_thread=check_same_thread)
        con.set_trace_callback(statements.append)
        return con
    monkeypatch.setattr(sqlite3, "connect", connect)
    return statements


def database(tmp_path: Path) -> Path:
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    con.close()
    return path


def checked(statements: list[str]) -> int:
    return sum(query.upper() == "PRAGMA QUICK_CHECK" for query in statements)


def test_start_uses_one_ordinary_writer_and_closes_it(tmp_path: Path, observed: list[str]) -> None:
    path = database(tmp_path)
    observed.clear()
    with open_start(path, tmp_path / "evidence", GitViews(30)) as start:
        assert not isinstance(start, Failed)
        # These are real composition objects; their public connection ports perform no external action.
        connections: list[sqlite3.Connection | None] = []
        admission = start.admission
        assert hasattr(admission, "connect")
        connections.append(admission.connect())
        assert hasattr(start.advance, "connect")
        connections.append(start.advance.connect())
        assert hasattr(start.checks.admission, "connect")
        connections.append(start.checks.admission.connect())
        assert all(con is connections[0] for con in connections) and checked(observed) == 1
    assert connections[0] is not None
    with pytest.raises(sqlite3.ProgrammingError):
        connections[0].execute("SELECT 1")


def test_land_and_round_writer_share_but_registration_keeps_its_own_timeout(tmp_path: Path, observed: list[str]) -> None:
    path = database(tmp_path)
    ordinary, registration = Store(SCHEMA), Store(SCHEMA)
    observed.clear()
    try:
        original = ordinary.shared_rw(path)
        assert original is not None
        for _ in range(3):
            with open_land(path, tmp_path / "evidence", GitViews(30), ordinary, registration) as land:
                assert not isinstance(land, Failed)
                assert land.work.store.connect() is original
                assert land.work.setups.registering.connect() is not None
                assert original.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        assert checked(observed) == 2  # both writers survive all three round compositions
    finally:
        registration.close_shared()
        ordinary.close_shared()


def test_entry_ordinary_and_bounded_connections_remain_distinct(tmp_path: Path, observed: list[str]) -> None:
    path = database(tmp_path)
    ordinary, registration = Store(SCHEMA), Store(SCHEMA)
    observed.clear()
    try:
        work = open_checking(path, tmp_path / "evidence", GitViews(30), ordinary, registration)
        main = work.store.connect()
        assert main is not None
        # Setup's registration reader is the public port used for command identity writes.
        assert work.setups.registering is not None
        bounded = work.setups.registering.connect()
        assert bounded is not None and bounded is not main
        assert main.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        assert bounded.execute("PRAGMA busy_timeout").fetchone() == (REGISTRATION_BUSY_MS,)
        assert checked(observed) == 2
    finally:
        registration.close_shared()
        ordinary.close_shared()


def test_reopening_and_replacement_keep_automatic_integrity_checks(tmp_path: Path, observed: list[str]) -> None:
    path = database(tmp_path)
    store = Store(SCHEMA)
    observed.clear()
    try:
        first = store.shared_rw(path)
        assert first is not None and checked(observed) == 1
        store.close_shared()
        reopened = store.shared_rw(path)
        assert reopened is not first and checked(observed) == 1
        path.rename(tmp_path / "preserved.db")
        replacement = Store(SCHEMA).open_rw(path)
        assert replacement is not None
        replacement.close()
        before = checked(observed)
        current = store.shared_rw(path)
        assert current is not None and current is not reopened and checked(observed) == before + 1
    finally:
        store.close_shared()


def test_shared_lifetime_keeps_separate_connections_per_thread(tmp_path: Path) -> None:
    path = database(tmp_path)
    ordinary, registration = Store(SCHEMA), Store(SCHEMA)
    work = open_checking(path, tmp_path / "evidence", GitViews(30), ordinary, registration)
    main = work.store.connect()
    found: list[sqlite3.Connection | None] = []
    def read() -> None:
        found.append(work.store.connect())
    thread = threading.Thread(target=read)
    try:
        thread.start()
        thread.join()
        assert found[0] is not None and main is not None and found[0] is not main
    finally:
        registration.close_shared()
        ordinary.close_shared()
