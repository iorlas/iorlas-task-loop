"""The launch check of factory.db's parts: create, adopt, upgrade, and the three refusals."""
import sqlite3

import pytest
import support.paths  # noqa: F401
from sqlite_store import SchemaError

from taskloop.app.parts import STAGE_PARTS
from tlkernel import dbparts, factorydb
from tlkernel.checks import PassRecord
from tlkernel.dbparts import Part, Prune


def con():
    c = sqlite3.connect(":memory:", isolation_level=None)
    return c


def part(version=1, ddl="CREATE TABLE t (a INTEGER);", records=(), steps=None):
    return Part(name="p", version=version, tables=("t",), ddl=ddl, records=records, steps=steps or {})


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


def test_read_only_without_needs_accepts_absent_and_older_parts():
    c = con()
    dbparts.launch(c, readonly=True, parts=[part()])
    assert c.execute("SELECT 1 FROM sqlite_master").fetchone() is None
    dbparts.launch(c, readonly=False, parts=[part()])
    dbparts.launch(c, readonly=True, parts=[part(version=2)])


@pytest.mark.parametrize("found", [0, 1])
def test_read_only_refuses_parts_below_need(found):
    c = con()
    if found:
        dbparts.launch(c, readonly=False, parts=[part()])
    with pytest.raises(SchemaError, match=f"p is v{found}, this process needs v2: the writer has not upgraded it yet"):
        dbparts.launch(c, readonly=True, parts=[part(version=2)], needs={"p": 2})


def test_read_only_accepts_met_need():
    c = con()
    dbparts.launch(c, readonly=False, parts=[part()])
    dbparts.launch(c, readonly=True, parts=[part(version=2)], needs={"p": 1})


def test_unknown_needed_part_is_refused():
    with pytest.raises(ValueError, match="unknown"):
        dbparts.launch(con(), readonly=True, parts=[part()], needs={"unknown": 1})


def test_a_table_claimed_by_two_parts_is_refused():
    with pytest.raises(ValueError, match="registered twice"):
        dbparts.ddl([part(), part()])
    with pytest.raises(ValueError, match="already belongs to part"):
        dbparts.ddl([part(), Part(name="q", version=1, tables=("t",), ddl="CREATE TABLE t (a INTEGER);")])


def two(name, rules, table):
    return Part(name=name, version=1, tables=(table,), ddl=f"CREATE TABLE {table} (a INTEGER);", prune=tuple(rules))


def test_prune_order_puts_children_before_parents_across_parts():
    parent = two("a", [Prune("parent", "1", after=("child",))], "parent")
    child = two("b", [Prune("child", "1")], "child")
    assert [r.table for r in dbparts.prune_order([parent, child])] == ["child", "parent"]
    assert [r.table for r in dbparts.prune_order([child, parent])] == ["child", "parent"]


def test_prune_order_refuses_a_cycle_and_a_rule_nobody_declares():
    a = two("a", [Prune("x", "1", after=("y",))], "x")
    b = two("b", [Prune("y", "1", after=("x",))], "y")
    with pytest.raises(ValueError, match="wait for each other"):
        dbparts.prune_order([a, b])
    with pytest.raises(ValueError, match="which no part prunes"):
        dbparts.prune_order([a])


def test_a_part_prunes_only_its_own_tables():
    with pytest.raises(ValueError, match="which is not its table"):
        dbparts.ddl([two("a", [Prune("other", "1")], "t")])


def test_the_registered_rules_delete_children_before_the_run():
    order = [r.table for r in dbparts.prune_order(STAGE_PARTS)]
    assert order.index("run") > max(order.index(t) for t in ("step", "attempt", "effect", "timed", "check_round"))


def test_undeclared_writer_refused_and_reader_allowed(tmp_path, monkeypatch):
    path = tmp_path / "factory.db"
    writer = factorydb.open_rw(path)
    assert writer is not None
    writer.close()
    monkeypatch.setattr(factorydb._STORE, "parts", None)
    with pytest.raises(SchemaError, match=r"factory.db opened before this process declared its parts \(factorydb.declare_parts\)"):
        factorydb.open_rw(path)
    reader = factorydb.open_ro(path)
    assert reader is not None
    reader.close()


def test_parts_cannot_be_redeclared_differently(monkeypatch):
    monkeypatch.setattr(factorydb._STORE, "parts", None)
    factorydb.declare_parts(STAGE_PARTS)
    factorydb.declare_parts(STAGE_PARTS)
    with pytest.raises(ValueError, match="different list"):
        factorydb.declare_parts(STAGE_PARTS[:-1])


@pytest.mark.parametrize("readonly", [False, True])
def test_launch_validates_part_ownership_before_touching_database(readonly):
    c = con()
    with pytest.raises(ValueError, match="registered twice"):
        dbparts.launch(c, readonly=readonly, parts=[part(), part()])
    other = Part(name="q", version=1, tables=("t",), ddl="CREATE TABLE t (a INTEGER);")
    with pytest.raises(ValueError, match="already belongs to part"):
        dbparts.launch(c, readonly=readonly, parts=[part(), other])
    assert c.execute("SELECT name FROM sqlite_master").fetchall() == []
