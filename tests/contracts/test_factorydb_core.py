"""Factory schema, independent opens, retention and WAL transaction guarantees."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlite_store
from sqlite_store import filesystem
from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from tlkernel import factorydb
from tlkernel.factoryparts import KV
from tlkernel.looprows import LoopRows
from tlkernel.paths import ConfigDir

TABLES = {
    "source",
    "bead",
    "run",
    "attempt",
    "step",
    "lease",
    "check_pass",
    "check_round",
    "ask",
    "ask_ledger",
    "kv",
    "effect",
    "wait",
    "signal",
    "checkpoint",
    "timed",
    "schema_part",
    "release_doc",
    "report_doc",
    "work_doc",
    "loop_doc",
    "look_doc",
    "lanes_doc",
    "followup",
    "park",
    "receipt_doc",
    "bead_doc",
    "repos_doc",
    "ticket_doc",
    "index_doc",
}

INDEXES = {
    "run_bead", "run_recent", "run_live", "bead_status", "check_tree", "ask_live",
}


class FactoryDbTest(Case):
    def setup_method(self):
        factorydb.clear_filesystem_cache()
        self.addCleanup(factorydb.clear_filesystem_cache)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "factory.db"

    def rw(self):
        con = factorydb.open_rw(self.path)
        if con is None:
            pytest.fail("fresh local factory database should open")
        self.addCleanup(con.close)
        return con

    def ro(self):
        con = factorydb.open_ro(self.path)
        if con is None:
            pytest.fail("existing WAL database should open read-only")
        self.addCleanup(con.close)
        return con

    def seed_ask(self, con):
        with factorydb.begin_immediate(con):
            con.execute("INSERT INTO ask(bead,id,status,t,body) VALUES ('b','a','open',1,'{}')")

    def test_fresh_open_creates_schema_and_pragmas(self):
        con = self.rw()
        assert con.execute("PRAGMA user_version").fetchone() == (factorydb.SCHEMA_VERSION,)
        assert con.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert con.execute("PRAGMA synchronous").fetchone() == (1,)
        assert con.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        assert con.execute("PRAGMA foreign_keys").fetchone() == (1,)
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert tables == TABLES
        assert indexes >= INDEXES

    def test_wraps_vendored_store_and_closes_shared_writer(self):
        assert isinstance(factorydb._STORE, sqlite_store.Store)
        self.seed_ask(self.rw())
        assert self.rw().execute("SELECT bead FROM ask").fetchall() == [("b",)]
        shared = factorydb.shared_rw(self.path)
        assert shared is not None
        self.addCleanup(factorydb.close_shared)
        assert shared.execute("SELECT bead FROM ask").fetchall() == [("b",)]
        factorydb.close_shared()
        with pytest.raises(sqlite3.ProgrammingError):
            shared.execute("SELECT 1")

    def test_reopen_preserves_rows(self):
        self.seed_ask(self.rw())
        assert self.rw().execute("SELECT bead,rev FROM ask").fetchall() == [("b", 0)]

    def test_wrong_version_is_rejected_without_replacing_it(self):
        con = self.rw()
        con.execute("PRAGMA user_version=99")
        with pytest.raises(factorydb.DatabaseError, match=r"factory\.db is schema v99.*knows v5.*update it"):
            factorydb.open_rw(self.path)
        with pytest.raises(factorydb.DatabaseError, match=r"factory\.db is schema v99.*knows v5.*update it"):
            factorydb.open_ro(self.path)
        assert con.execute("PRAGMA user_version").fetchone() == (99,)

    def test_unversioned_nonempty_database_is_not_initialized(self):
        con = sqlite3.connect(self.path)
        self.addCleanup(con.close)
        con.execute("CREATE TABLE unrelated (value TEXT)")
        assert factorydb.open_rw(self.path) is None
        assert con.execute("PRAGMA user_version").fetchone() == (0,)

    def test_corrupt_bytes_are_rejected(self):
        self.path.write_bytes(b"this is not a SQLite database")
        assert factorydb.open_rw(self.path) is None
        assert factorydb.open_ro(self.path) is None

    def test_non_wal_database_is_rejected(self):
        assert factorydb.open_rw(":memory:") is None
        con = sqlite3.connect(self.path)
        self.addCleanup(con.close)
        con.execute("PRAGMA user_version=1")
        with pytest.raises(factorydb.DatabaseError, match="the writer has not upgraded it yet"):
            factorydb.open_ro(self.path)

    def test_missing_read_only_database_stays_missing(self):
        assert factorydb.open_ro(self.path) is None
        assert not self.path.exists()

    def test_read_only_connection_cannot_write(self):
        self.rw()
        con = self.ro()
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO kv(k,v,t) VALUES ('key','value',1)")

    def test_cas_advances_once_and_rejects_stale_revision(self):
        con = self.rw()
        self.seed_ask(con)
        with factorydb.begin_immediate(con):
            assert factorydb.cas_update(con, "ask", "bead", "b", 0, status="answered")
            assert not factorydb.cas_update(con, "ask", "bead", "b", 0, status="stale")
        assert con.execute("SELECT status,rev FROM ask").fetchone() == ("answered", 1)

    def test_cas_updates_run_rows_and_rejects_stale_revision(self):
        con = self.rw()
        con.execute(
            "INSERT INTO run(run,repo,repo_key,state,started,manifest) "
            "VALUES ('r','/repo','repo','running',1,'{}')")
        with factorydb.begin_immediate(con):
            assert factorydb.cas_update(con, "run", "run", "r", 0, state="done")
            assert not factorydb.cas_update(con, "run", "run", "r", 0, state="stale")
        assert con.execute("SELECT state,rev FROM run").fetchone() == ("done", 1)

    def test_owners_cover_exactly_the_created_tables(self):
        tables = {row[0] for row in self.rw().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(factorydb.OWNERS) == tables - {"schema_part"}  # the kernel's own table: every open writes it
        assert set(factorydb.OWNERS.values()) <= {"index", "engine", "loop", "owner", "gate"}

    def test_cas_rejects_unrevisioned_tables_and_missing_transaction(self):
        con = self.rw()
        with pytest.raises(ValueError, match="transaction"):
            factorydb.cas_update(con, "ask", "bead", "b", 0, status="answered")
        with factorydb.begin_immediate(con):
            for table in TABLES - {"run", "ask", "bead", "checkpoint"}:
                with self.subTest(table=table), pytest.raises(ValueError, match="unrevisioned"):
                    factorydb.cas_update(con, table, "id", "key", 0)

    def test_only_revisioned_tables_are_cas_targets(self):
        con = self.rw()
        revisioned = {table for table in TABLES if "rev" in {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}}
        assert revisioned == factorydb.REVISIONED_TABLES

    def test_wal_reader_keeps_snapshot_across_writer_commit(self):
        writer = self.rw()
        self.seed_ask(writer)
        reader = self.ro()
        reader.execute("BEGIN")
        assert reader.execute("SELECT rev FROM ask").fetchone() == (0,)
        with factorydb.begin_immediate(writer):
            assert factorydb.cas_update(writer, "ask", "bead", "b", 0, status="answered")
            assert reader.execute("SELECT rev FROM ask").fetchone() == (0,)
        assert reader.execute("SELECT rev FROM ask").fetchone() == (0,)
        reader.commit()
        assert reader.execute("SELECT rev FROM ask").fetchone() == (1,)

    def test_unsafe_filesystem_is_rejected_before_connecting(self):
        with patch.object(filesystem, "_unsafe_filesystem", return_value=True):
            assert factorydb.open_rw(self.path) is None
            assert factorydb.open_ro(self.path) is None
        assert not self.path.exists()

    def test_run_has_no_family_authority_or_writer_column(self):
        con = self.rw()
        assert con.execute("SELECT name FROM sqlite_master WHERE name='family'").fetchall() == []
        columns = {r[1]: r for r in con.execute("PRAGMA table_info(run)")}
        assert "writer" not in columns
        assert columns["manifest"][3] == 1

    def test_bead_projection_is_index_owned_and_revisioned(self):
        con = self.rw()
        assert factorydb.OWNERS["bead"] == "index"
        assert con.execute("PRAGMA foreign_key_list(bead)").fetchall() == []
        con.execute("INSERT INTO bead(id,repo_key,status,updated,fetched) VALUES ('opaque.id','repo','open',1,2)")
        assert con.execute("SELECT title,priority,type,parent,assignee,labels,rev,body FROM bead").fetchone() == (
            "", None, "", "", "", "[]", 0, "{}")
        with factorydb.begin_immediate(con):
            assert factorydb.cas_update(con, "bead", "id", "opaque.id", 0, parent="unrelated", status="closed")
            assert not factorydb.cas_update(con, "bead", "id", "opaque.id", 0, status="stale")
        assert con.execute("SELECT parent,status,rev FROM bead").fetchone() == ("unrelated", "closed", 1)

    def seed_history(self, con, run="old", state="done", ended=2):
        con.execute(
            "INSERT INTO run(run,repo,repo_key,bead,state,started,ended,manifest) VALUES (?,'repo','repo',?,?,1,?,'{}')",
            (run, run, state, ended),
        )
        con.execute("INSERT INTO attempt(run,n,started,ended) VALUES (?,1,1,2)", (run,))
        con.execute("INSERT INTO step(run,key,try,attempt,status,started,ended) VALUES (?,'s',1,1,'ok',1,2)", (run,))
        con.execute("INSERT INTO effect(key,run,name,state,intent_at,done_at) VALUES (?,?,'e','done',1,2)", (run, run))
        con.execute("INSERT INTO check_round(run,round,ts,body) VALUES (?,1,2,'{}')", (run,))
        con.execute("INSERT INTO timed(run,bead,kind,name,exec_s,wait_s,t) VALUES (?,?,'step','s',1,0,2)", (run, run))

    def test_prune_deletes_old_finished_history_and_returns_counts(self):
        con = self.rw()
        self.seed_history(con)
        con.execute("INSERT INTO ask(bead,id,status,t,body) VALUES ('old','a','answered',1,'{}')")
        con.execute("INSERT INTO ask_ledger(t,event,ask,bead,body,origin) VALUES (2,'answer','a','old','{}','o')")
        con.execute("INSERT INTO ask_ledger(t,event,body,origin) VALUES (10,'answer','{}','recent')")
        counts = factorydb.prune_older_than(con, 10)
        assert counts == dict.fromkeys(("ask_ledger", "check_round", "step", "attempt", "effect", "timed", "run"), 1)
        assert con.execute("SELECT origin FROM ask_ledger").fetchall() == [("recent",)]
        assert con.execute("SELECT status FROM ask").fetchall() == [("answered",)]
        assert not con.in_transaction
        assert all(count == 0 for count in factorydb.prune_older_than(con, 10).values())

    def test_prune_keeps_live_recent_and_referenced_runs_with_their_history(self):
        con = self.rw()
        for run, state, ended in (
            ("running", "running", 2), ("created", "created", 2), ("unfinished", "done", None),
            ("recent", "done", 10), ("lease", "done", 2), ("wait", "done", 2),
            ("signal", "done", 2), ("ask", "done", 2), ("soft", "done", 2),
        ):
            self.seed_history(con, run, state, ended)
        con.execute("INSERT INTO lease(kind,name,holder,run,since) VALUES ('run','l','h','lease',1)")
        con.execute("INSERT INTO wait(repo,run,kind,since) VALUES ('repo','wait','lane',1)")
        con.execute("INSERT INTO signal(run,kind,at) VALUES ('signal','stop',1)")
        for bead, status in (("ask", "open"), ("soft", "open_soft")):
            con.execute("INSERT INTO ask(bead,id,status,t,body) VALUES (?,?,?,1,'{}')", (bead, bead, status))
        assert all(count == 0 for count in factorydb.prune_older_than(con, 10).values())
        for table in ("run", "attempt", "step", "effect", "check_round"):
            assert con.execute(f'SELECT count(*) FROM "{table}"').fetchone() == (9,)
        for table in ("lease", "wait", "signal"):
            assert con.execute(f'SELECT count(*) FROM "{table}"').fetchone() == (1,)
        assert con.execute("SELECT count(*) FROM ask").fetchone() == (2,)

    def test_prune_keeps_open_ask_and_running_run_audit(self):
        con = self.rw()
        self.seed_history(con, "running", "running")
        self.seed_ask(con)
        for bead in ("running", "b"):
            con.execute("INSERT INTO ask_ledger(t,event,bead,body,origin) VALUES (1,'state',?,'{}',?)", (bead, bead))
        assert all(count == 0 for count in factorydb.prune_older_than(con, 10).values())
        assert con.execute("SELECT count(*) FROM ask_ledger").fetchone() == (2,)

    def test_prune_consumed_signal_does_not_pin_history(self):
        con = self.rw()
        self.seed_history(con)
        con.execute("INSERT INTO signal(run,kind,at,taken) VALUES ('old','stop',1,2)")
        assert factorydb.prune_older_than(con, 10)["run"] == 1
        assert con.execute("SELECT taken FROM signal").fetchall() == [(2.0,)]

    def test_prune_standalone_gate_rounds_by_timestamp(self):
        con = self.rw()
        for number, ts in ((1, 2), (2, 10), (3, None)):
            con.execute("INSERT INTO check_round(run,round,ts,body) VALUES ('standalone',?,?,'{}')", (number, ts))
        assert factorydb.prune_older_than(con, 10, ("check_round",)) == {"check_round": 1}
        assert con.execute("SELECT round FROM check_round ORDER BY round").fetchall() == [(2,), (3,)]

    def test_prune_subset_keeps_parent_until_all_children_are_removed(self):
        con = self.rw()
        self.seed_history(con)
        assert factorydb.prune_older_than(con, 10, ("run",)) == {"run": 0}
        assert factorydb.prune_older_than(con, 10, ("step", "run")) == {"step": 1, "run": 0}
        assert (
            factorydb.prune_older_than(con, 10, ("attempt", "effect", "check_round", "timed", "run"))
            == {"check_round": 1, "attempt": 1, "effect": 1, "timed": 1, "run": 1}
        )

    def test_prune_rejects_state_tables_before_deleting_anything(self):
        con = self.rw()
        self.seed_history(con)
        for table in TABLES - {"ask_ledger", "check_round", "step", "attempt", "effect", "timed", "run"}:
            with self.subTest(table=table), pytest.raises(ValueError, match="history"):
                factorydb.prune_older_than(con, 10, ("step", table))
        assert con.execute("SELECT count(*) FROM step").fetchone() == (1,)

    def test_prune_rolls_back_all_deletes_if_parent_delete_fails(self):
        con = self.rw()
        self.seed_history(con)
        con.execute("CREATE TRIGGER retain_run BEFORE DELETE ON run BEGIN SELECT RAISE(ABORT,'retain'); END")
        with pytest.raises(sqlite3.IntegrityError, match="retain"):
            factorydb.prune_older_than(con, 10)
        for table in ("run", "attempt", "step", "effect", "check_round"):
            assert con.execute(f'SELECT count(*) FROM "{table}"').fetchone() == (1,)
        assert not con.in_transaction


def test_a_reader_meets_a_database_a_writer_is_still_creating_as_not_there_yet(tmp_path):
    """Two processes starting on a fresh factory.db: the file exists at user_version 0 until the first writer's DDL commits. A reader
    (the loop's own rows, the dashboard) must see no rows, not a SchemaError (shelf sqlite-store bf97aba)."""
    cfg = ConfigDir(tmp_path)
    cfg.factory_db().parent.mkdir(parents=True, exist_ok=True)
    cfg.factory_db().touch()
    assert factorydb.open_ro(cfg.factory_db()) is None
    assert LoopRows(cfg, "k").select("SELECT 1") == []


def test_declared_versions_and_reader_needs(tmp_path, monkeypatch):
    monkeypatch.setattr(factorydb._STORE, "parts", None)
    monkeypatch.setattr(factorydb._STORE, "needs", None)
    monkeypatch.setattr(factorydb._STORE, "schema", factorydb.SCHEMA)
    factorydb.declare_parts([KV])
    assert factorydb.versions() == {"kv": KV.version}
    path = tmp_path / "factory.db"
    con = factorydb.open_rw(path)
    assert con is not None
    con.execute("DELETE FROM schema_part WHERE name='kv'")
    con.close()
    reader = factorydb.open_ro(path)
    assert reader is not None
    reader.close()
    factorydb.declare_needs({"kv": 1})
    factorydb.declare_needs({"kv": 1})
    with pytest.raises(ValueError, match="different versions"):
        factorydb.declare_needs({"kv": 2})
    for opener in (factorydb.open_ro, factorydb.open_watch):
        with pytest.raises(factorydb.SchemaError, match="part kv is v0, this process needs v1"):
            opener(path)
