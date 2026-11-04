"""Factory schema compatibility and authoritative upgrades through sqlite_store."""

import sqlite3
from dataclasses import replace
from unittest.mock import patch

import pytest
import support.paths  # noqa: F401
from sqlite_store import Store
from support.narrow import must

from taskloop.contracts import factorydb


def add_summary(con: sqlite3.Connection) -> None:
    con.execute("ALTER TABLE run ADD COLUMN summary TEXT")
    con.execute("UPDATE run SET summary=state || ':' || bead")


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "factory.db"
    con = must(factorydb.open_rw(path))
    con.execute(
        "INSERT INTO run(run,repo,repo_key,bead,state,started,manifest) "
        "VALUES ('r','/repo','repo','b','running',1,'{}')")
    con.execute("INSERT INTO attempt(run,n,started) VALUES ('r',1,2)")
    con.execute("INSERT INTO step(run,key,try,attempt,status,started) VALUES ('r','build',1,1,'done',3)")
    try:
        yield path, con
    finally:
        con.close()


def authoritative_rows(con):
    return {table: con.execute(f"SELECT * FROM {table}").fetchall() for table in ("run", "attempt", "step")}


def test_newer_schema_refuses_both_opens_without_quarantine(database):
    path, con = database
    found = factorydb.SCHEMA_VERSION + 1
    con.execute(f"PRAGMA user_version={found}")
    original = authoritative_rows(con)
    message = rf"factory\.db is schema v{found}.*knows v{factorydb.SCHEMA_VERSION}.*update it"
    for opener in (factorydb.open_rw, factorydb.open_ro):
        with pytest.raises(factorydb.SchemaError, match=message):
            opener(path)
    assert con.execute("PRAGMA user_version").fetchone() == (found,)
    assert authoritative_rows(con) == original
    assert list(path.parent.glob("factory.db.bad-*")) == []


def test_older_reader_refuses_then_writer_upgrades_in_place(database):
    path, con = database
    identity = path.stat().st_ino
    original = authoritative_rows(con)
    schema = replace(factorydb.SCHEMA, version=3, steps={2: add_summary})
    with patch.object(factorydb, "_STORE", Store(schema)):
        message = r"factory\.db is schema v2.*knows v3.*the writer has not upgraded it yet"
        with pytest.raises(factorydb.SchemaError, match=message):
            factorydb.open_ro(path)
        assert con.execute("PRAGMA user_version").fetchone() == (2,)
        writer = must(factorydb.open_rw(path))
        writer.close()
        reader = must(factorydb.open_ro(path))
        try:
            assert reader.execute("SELECT summary FROM run").fetchone() == ("running:b",)
        finally:
            reader.close()
    assert path.stat().st_ino == identity
    for table, rows in original.items():
        columns = len(rows[0])
        assert [row[:columns] for row in con.execute(f"SELECT * FROM {table}")] == rows
    assert list(path.parent.glob("factory.db.bad-*")) == []


def test_writer_reports_upgrade_failure_without_quarantine(database):
    path, con = database
    original = authoritative_rows(con)
    schema = replace(factorydb.SCHEMA, version=3, steps={})
    with patch.object(factorydb, "_STORE", Store(schema)), \
            pytest.raises(factorydb.SchemaError, match=r"factory\.db missing upgrade step v2 -> v3"):
        factorydb.open_rw(path)
    assert con.execute("PRAGMA user_version").fetchone() == (2,)
    assert authoritative_rows(con) == original
    assert list(path.parent.glob("factory.db.bad-*")) == []
