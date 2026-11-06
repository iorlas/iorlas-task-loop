"""Factory schema compatibility and authoritative upgrades through sqlite_store."""

import sqlite3
from dataclasses import replace
from unittest.mock import patch

import pytest
import support.paths  # noqa: F401
from sqlite_store import Store
from support.narrow import must

from taskloop.contracts import factorydb

# Frozen v2 schema, deliberately independent of the current factorydb.DDL.
V2_DDL = """
CREATE TABLE source (path TEXT PRIMARY KEY, family TEXT NOT NULL,
  dev INTEGER, ino INTEGER, size INTEGER, mtime_ns INTEGER, head TEXT,
  offset INTEGER NOT NULL DEFAULT 0, seen REAL NOT NULL, error TEXT);
CREATE TABLE bead (id TEXT PRIMARY KEY, repo_key TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
  priority INTEGER, type TEXT NOT NULL DEFAULT '', parent TEXT NOT NULL DEFAULT '', assignee TEXT NOT NULL DEFAULT '',
  labels TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL, fetched REAL NOT NULL, rev INTEGER NOT NULL DEFAULT 0);
CREATE INDEX bead_status ON bead(repo_key, status);
CREATE TABLE run (run TEXT PRIMARY KEY, repo TEXT NOT NULL, repo_key TEXT NOT NULL, bead TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT '', owner TEXT, session TEXT, loop TEXT, worktree TEXT, branch TEXT, sha TEXT,
  state TEXT NOT NULL, reason TEXT, started REAL NOT NULL, ended REAL, next_step TEXT,
  outcome TEXT, why TEXT, version TEXT, stats TEXT, bundle TEXT, facts TEXT, facts_upto INTEGER,
  manifest TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 0);
CREATE INDEX run_bead ON run(bead, started);
CREATE INDEX run_recent ON run(repo_key, started);
CREATE INDEX run_live ON run(state) WHERE state IN ('created','running');
CREATE TABLE attempt (run TEXT NOT NULL REFERENCES run, n INTEGER NOT NULL, host TEXT, pid INTEGER, start_id TEXT,
  started REAL NOT NULL, beat REAL, ended REAL, end_kind TEXT, fault_class TEXT, fingerprint TEXT, reason TEXT,
  PRIMARY KEY (run, n));
CREATE TABLE step (run TEXT NOT NULL REFERENCES run, key TEXT NOT NULL, try INTEGER NOT NULL, attempt INTEGER NOT NULL,
  status TEXT NOT NULL, started REAL NOT NULL, ended REAL, input_digest TEXT, result TEXT, fingerprint TEXT, calls INTEGER DEFAULT 0,
  PRIMARY KEY (run, key, try));
CREATE TABLE lease (kind TEXT NOT NULL CHECK (kind IN ('run','loop','resource','slot')), name TEXT NOT NULL,
  holder TEXT NOT NULL, run TEXT, host TEXT, pid INTEGER, start_id TEXT, since REAL NOT NULL, beat REAL, until REAL,
  body TEXT, PRIMARY KEY (kind, name));
CREATE TABLE check_pass (repo_key TEXT NOT NULL, check_id TEXT NOT NULL, digest TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('pass','base_red')), tree TEXT, base TEXT, run TEXT, host TEXT, ts REAL NOT NULL,
  body TEXT NOT NULL, PRIMARY KEY (repo_key, check_id, digest, kind));
CREATE INDEX check_tree ON check_pass(repo_key, tree, base);
CREATE TABLE check_round (run TEXT NOT NULL, round INTEGER NOT NULL, ts REAL, body TEXT NOT NULL, PRIMARY KEY (run, round));
CREATE TABLE ask (bead TEXT PRIMARY KEY, id TEXT NOT NULL, repo TEXT, status TEXT NOT NULL, t REAL NOT NULL, consumed REAL,
  body TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ask_live ON ask(status, t);
CREATE TABLE ask_ledger (id INTEGER PRIMARY KEY, t REAL NOT NULL, event TEXT NOT NULL, ask TEXT, bead TEXT, repo TEXT,
  body TEXT NOT NULL, origin TEXT NOT NULL UNIQUE);
CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, t REAL NOT NULL, stamp TEXT);
CREATE TABLE effect (key TEXT PRIMARY KEY, run TEXT NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL,
  intent_at REAL NOT NULL, done_at REAL, receipt TEXT);
CREATE TABLE wait (id INTEGER PRIMARY KEY, repo TEXT NOT NULL, run TEXT, kind TEXT NOT NULL,
  wake_at REAL, wake_on TEXT, facts TEXT, since REAL NOT NULL, cleared REAL);
CREATE TABLE signal (id INTEGER PRIMARY KEY, run TEXT, kind TEXT NOT NULL, payload TEXT, at REAL NOT NULL, taken REAL);
"""


def test_real_v2_database_upgrades_in_place_preserving_rows(tmp_path):
    path = tmp_path / "factory.db"
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(V2_DDL)
        con.execute("PRAGMA user_version=2")
        con.execute("INSERT INTO bead(id,repo_key,status,updated,fetched,rev) VALUES ('b','repo','open',1,2,7)")
        con.execute("INSERT INTO run(run,repo,repo_key,state,started,manifest) VALUES ('r','/repo','repo','done',1,'{}')")
        before = con.execute("SELECT * FROM bead").fetchone()
        run = con.execute("SELECT * FROM run").fetchone()
    finally:
        con.close()
    inode = path.stat().st_ino
    with pytest.raises(factorydb.SchemaError, match="the writer has not upgraded it yet"):
        factorydb.open_ro(path)
    writer = must(factorydb.open_rw(path))
    try:
        assert writer.execute("PRAGMA user_version").fetchone() == (factorydb.SCHEMA_VERSION,)
        assert writer.execute("SELECT * FROM bead").fetchone() == (*before, "{}")
        assert writer.execute("SELECT * FROM run").fetchone() == run
    finally:
        writer.close()
    reader = must(factorydb.open_ro(path))
    reader.close()
    assert path.stat().st_ino == inode
    assert list(tmp_path.glob("factory.db.bad-*")) == []


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
    here = factorydb.SCHEMA_VERSION
    schema = replace(factorydb.SCHEMA, version=here + 1, steps={**factorydb.SCHEMA.steps, here: add_summary})
    with patch.object(factorydb, "_STORE", Store(schema)):
        message = rf"factory\.db is schema v{here}.*knows v{here + 1}.*the writer has not upgraded it yet"
        with pytest.raises(factorydb.SchemaError, match=message):
            factorydb.open_ro(path)
        assert con.execute("PRAGMA user_version").fetchone() == (here,)
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
    here = factorydb.SCHEMA_VERSION
    schema = replace(factorydb.SCHEMA, version=here + 1, steps=dict(factorydb.SCHEMA.steps))
    with patch.object(factorydb, "_STORE", Store(schema)), \
            pytest.raises(factorydb.SchemaError, match=rf"factory\.db missing upgrade step v{here} -> v{here + 1}"):
        factorydb.open_rw(path)
    assert con.execute("PRAGMA user_version").fetchone() == (here,)
    assert authoritative_rows(con) == original
    assert list(path.parent.glob("factory.db.bad-*")) == []
