"""A persistent read-only watcher notices commits, with deterministic wait budgets."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from tlkernel import factorydb
from tlkernel.paths import ConfigDir

from tldash.readers.wake import Wake, wait_seconds


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def journal(tmp_path: Path) -> Iterator[tuple[ConfigDir, sqlite3.Connection, Wake, Clock]]:
    cfg, clock = ConfigDir(tmp_path), Clock()
    con = factorydb.open_rw(cfg.factory_db())
    assert con is not None
    wake = Wake(cfg, clock.sleep, clock)
    try:
        yield cfg, con, wake, clock
    finally:
        wake.close()
        con.close()


def commit(con: sqlite3.Connection) -> None:
    with factorydb.begin_immediate(con):
        con.execute("INSERT OR REPLACE INTO look_doc(k,v,t) VALUES ('wake','changed',1)")


def test_token_changes_only_after_another_connection_commits(journal) -> None:
    _, con, wake, _ = journal
    before = wake.token()
    assert before is not None
    assert wake.token() == before
    assert wake.con is not None
    assert before == factorydb.change_counter(wake.con)
    wake.con.execute("SELECT * FROM look_doc").fetchall()
    assert wake.token() == before
    con.execute("BEGIN IMMEDIATE")
    con.execute("INSERT INTO look_doc(k,v,t) VALUES ('uncommitted','x',1)")
    assert wake.token() == before
    con.commit()
    assert wake.token() != before
    with pytest.raises(sqlite3.OperationalError):
        wake.con.execute("INSERT INTO look_doc(k,v,t) VALUES ('forbidden','x',1)")


def test_wait_returns_immediately_for_an_already_changed_token(journal) -> None:
    _, con, wake, clock = journal
    before = wake.token()
    commit(con)
    assert wake.wait(before, 20) != before
    assert clock.sleeps == []


def test_wait_notices_a_commit_in_one_iteration(journal) -> None:
    _, con, wake, clock = journal
    before = wake.token()

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        commit(con)

    wake.sleep = sleep
    assert wake.wait(before, 20) != before
    assert clock.sleeps == [0.05]


def test_wait_caps_the_budget_at_twenty_five_seconds(journal) -> None:
    _, _, wake, clock = journal
    before = wake.token()
    assert wake.wait(before, 1000) == before
    assert clock.now == 25
    assert max(clock.sleeps) <= 0.05


def test_wait_stops_when_the_database_becomes_unavailable(journal, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, wake, clock = journal
    before = wake.token()

    def unavailable(con: sqlite3.Connection) -> int:
        raise sqlite3.DatabaseError("database unavailable")

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        monkeypatch.setattr(factorydb, "change_counter", unavailable)

    wake.sleep = sleep
    assert wake.wait(before, 20) is None
    assert clock.sleeps == [0.05]
    assert wake.con is None


def test_unavailable_database_returns_none_and_can_reopen(tmp_path: Path) -> None:
    wake = Wake(ConfigDir(tmp_path), sleep=lambda _: pytest.fail("unavailable wait slept"))
    assert wake.token() is None
    assert wake.wait(None, 20) is None
    con = factorydb.open_rw(wake.cfg.factory_db())
    assert con is not None
    try:
        assert wake.token() is not None
        wake.close()
        assert wake.token() is not None
    finally:
        wake.close()
        con.close()


@pytest.mark.parametrize(("value", "expected"), [("bad", 0), ("nan", 0), ("-2", 0), ("inf", 25), ("99", 25), ("0.5", 0.5)])
def test_wait_parameter(value: str, expected: float) -> None:
    assert wait_seconds(value) == expected
