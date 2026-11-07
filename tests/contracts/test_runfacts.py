"""Run facts preserve authoritative rows and participate in caller transactions."""

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from tlkernel import factorydb, runfacts


@pytest.fixture
def con(tmp_path: Path) -> Generator[sqlite3.Connection]:
    connection = factorydb.open_rw(tmp_path / "factory.db")
    assert connection is not None
    try:
        yield connection
    finally:
        connection.close()


def insert_run(con: sqlite3.Connection, run: str) -> None:
    """Seed the required authoritative columns with a nonzero revision."""
    con.execute("INSERT INTO run (run,repo,repo_key,state,started,manifest,rev) VALUES (?,?,?,'running',1,'{}',7)",
                (run, "/repo", "repo"))


def test_empty_and_missing_runs(con: sqlite3.Connection) -> None:
    assert runfacts.count_runs(con) == 0
    assert runfacts.read_facts(con, "missing") is None
    with factorydb.begin_immediate(con):
        runfacts.write_facts(con, "missing", "{}", 10)
        runfacts.clear_facts(con)
    assert runfacts.count_runs(con) == 0


def test_roundtrip_updates_only_the_selected_runs_facts(con: sqlite3.Connection) -> None:
    with factorydb.begin_immediate(con):
        insert_run(con, "one")
        insert_run(con, "two")
        assert runfacts.read_facts(con, "one") is None
        runfacts.write_facts(con, "one", '{"log":"héllo"}', 42)
    assert runfacts.count_runs(con) == 2
    assert runfacts.read_facts(con, "one") == '{"log":"héllo"}'
    assert runfacts.read_facts(con, "two") is None
    with factorydb.begin_immediate(con):
        runfacts.write_facts(con, "one", "", 0)
    assert runfacts.read_facts(con, "one") == ""
    assert con.execute("SELECT run,facts_upto,state,manifest,rev FROM run ORDER BY run").fetchall() == [
        ("one", 0, "running", "{}", 7), ("two", None, "running", "{}", 7)]


def test_clear_resets_every_fold_and_offset_preserving_run_rows(con: sqlite3.Connection) -> None:
    with factorydb.begin_immediate(con):
        for run in ("one", "two"):
            insert_run(con, run)
            runfacts.write_facts(con, run, "{}", 42)
        runfacts.clear_facts(con)
    assert runfacts.count_runs(con) == 2
    assert con.execute("SELECT facts,facts_upto,state,manifest,rev FROM run").fetchall() == [
        (None, None, "running", "{}", 7), (None, None, "running", "{}", 7)]


@pytest.mark.parametrize("clear", (False, True))
def test_mutations_roll_back_with_the_callers_transaction(con: sqlite3.Connection, clear: bool) -> None:
    with factorydb.begin_immediate(con):
        insert_run(con, "one")
        runfacts.write_facts(con, "one", "original", 7)
    with pytest.raises(ValueError, match="abort"), factorydb.begin_immediate(con):
        runfacts.write_facts(con, "one", "replacement", 99)
        if clear:
            runfacts.clear_facts(con)
        assert con.in_transaction
        raise ValueError("abort")
    assert runfacts.read_facts(con, "one") == "original"
    assert con.execute("SELECT facts_upto FROM run").fetchone() == (7,)
