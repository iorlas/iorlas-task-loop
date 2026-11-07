"""The launch check of factory.db's parts: create, adopt, upgrade, and the three refusals."""
import sqlite3

import pytest
import support.paths  # noqa: F401
from sqlite_store import SchemaError

from taskloop.contracts import dbparts
from taskloop.contracts.checks import PassRecord
from taskloop.contracts.dbparts import Part


def con():
    c = sqlite3.connect(":memory:", isolation_level=None)
    return c


def part(version=1, ddl="CREATE TABLE t (a INTEGER);", records=(), steps=None, read_from=None):
    return Part(name="p", version=version, tables=("t",), ddl=ddl, records=records, steps=steps or {}, read_from=read_from)


def row(c):
    return c.execute("SELECT name, version FROM schema_part").fetchall()


def test_launch_creates_the_tables_and_the_row():
    c = con()
    dbparts.launch(c, readonly=False, parts=[part()])
    assert row(c) == [("p", 1)]
    c.execute("INSERT INTO t VALUES (1)")


def test_launch_adopts_existing_equal_tables():
    c = con()
    c.execute("CREATE TABLE t (\n  a   INTEGER\n)")
    dbparts.launch(c, readonly=False, parts=[part()])
    assert row(c) == [("p", 1)]


def test_launch_refuses_existing_tables_that_differ():
    c = con()
    c.execute("CREATE TABLE t (a TEXT)")
    with pytest.raises(SchemaError, match="changed without a bump"):
        dbparts.launch(c, readonly=False, parts=[part()])
    assert c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_part'").fetchone() is None


def test_launch_refuses_a_newer_database():
    c = con()
    dbparts.launch(c, readonly=False, parts=[part(version=2, steps={1: lambda c: None})])
    for readonly in (False, True):
        with pytest.raises(SchemaError, match=r"p is v2, this code knows v1: update it"):
            dbparts.launch(c, readonly=readonly, parts=[part()])


def test_launch_refuses_changed_ddl_at_the_same_version():
    c = con()
    dbparts.launch(c, readonly=False, parts=[part()])
    with pytest.raises(SchemaError, match=r"its tables .* changed without a bump"):
        dbparts.launch(c, readonly=False, parts=[part(ddl="CREATE TABLE t (a INTEGER, b TEXT);")])


def test_launch_refuses_a_changed_record_version_at_the_same_version(monkeypatch):
    c = con()
    dbparts.launch(c, readonly=False, parts=[part(records=(PassRecord,))])
    monkeypatch.setattr(PassRecord, "V", 2, raising=False)
    with pytest.raises(SchemaError, match="a record changed its V without a version bump"):
        dbparts.launch(c, readonly=False, parts=[part(records=(PassRecord,))])


def test_launch_runs_the_steps_in_one_transaction_and_moves_the_row():
    c = con()
    dbparts.launch(c, readonly=False, parts=[part()])
    c.execute("INSERT INTO t VALUES (7)")
    up = part(version=2, ddl="CREATE TABLE t (a INTEGER, b TEXT);", steps={1: lambda c: c.execute("ALTER TABLE t ADD COLUMN b TEXT")})
    dbparts.launch(c, readonly=False, parts=[up])
    assert row(c) == [("p", 2)]
    assert c.execute("SELECT a, b FROM t").fetchall() == [(7, None)]


def test_a_failing_step_changes_nothing():
    c = con()
    dbparts.launch(c, readonly=False, parts=[part()])

    def broken(c):
        c.execute("ALTER TABLE t ADD COLUMN b TEXT")
        raise RuntimeError("boom")

    with pytest.raises(SchemaError, match="step v1 -> v2 failed: boom"):
        dbparts.launch(c, readonly=False, parts=[part(version=2, ddl="CREATE TABLE t (a INTEGER, b TEXT);", steps={1: broken})])
    assert row(c) == [("p", 1)]
    assert [r[1] for r in c.execute("PRAGMA table_info(t)")] == ["a"]


def test_a_missing_step_is_refused():
    c = con()
    dbparts.launch(c, readonly=False, parts=[part()])
    with pytest.raises(SchemaError, match="missing the upgrade step v1 -> v2"):
        dbparts.launch(c, readonly=False, parts=[part(version=2)])


def test_read_only_launch_skips_a_part_without_a_row_and_refuses_an_old_one():
    c = con()
    dbparts.launch(c, readonly=True, parts=[part()])
    assert c.execute("SELECT 1 FROM sqlite_master").fetchone() is None
    dbparts.launch(c, readonly=False, parts=[part()])
    with pytest.raises(SchemaError, match="the writer has not upgraded it yet"):
        dbparts.launch(c, readonly=True, parts=[part(version=2)])
    dbparts.launch(c, readonly=True, parts=[part(version=2, read_from=1)])


def test_a_table_claimed_by_two_parts_is_refused(monkeypatch):
    monkeypatch.setattr(dbparts, "_REGISTRY", {})
    dbparts.register(part())
    with pytest.raises(ValueError, match="registered twice"):
        dbparts.register(part())
    with pytest.raises(ValueError, match="already belongs to part"):
        dbparts.register(Part(name="q", version=1, tables=("t",), ddl="CREATE TABLE t (a INTEGER);"))
