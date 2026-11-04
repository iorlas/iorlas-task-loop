"""Factory schema, rejected database opens and WAL transaction guarantees."""

import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import factorydb

TABLES = {
    "source", "bead", "run", "attempt", "step", "lease", "check_pass",
    "check_round", "ask", "ask_ledger", "kv", "effect", "wait", "signal",
}
INDEXES = {
    "run_bead", "run_recent", "run_live", "bead_status", "check_tree", "ask_live",
}


class FactoryDbTest(unittest.TestCase):
    def setUp(self):
        cache = patch.object(factorydb, "_CHECKED", set())
        cache.start()
        self.addCleanup(cache.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "factory.db"

    def rw(self):
        con = factorydb.open_rw(self.path)
        if con is None:
            self.fail("fresh local factory database should open")
        self.addCleanup(con.close)
        return con

    def ro(self):
        con = factorydb.open_ro(self.path)
        if con is None:
            self.fail("existing WAL database should open read-only")
        self.addCleanup(con.close)
        return con

    def seed_ask(self, con):
        with factorydb.begin_immediate(con):
            con.execute("INSERT INTO ask(bead,id,status,t,body) VALUES ('b','a','open',1,'{}')")

    def test_fresh_open_creates_schema_and_pragmas(self):
        con = self.rw()
        self.assertEqual(con.execute("PRAGMA user_version").fetchone(), (2,))
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone(), ("wal",))
        self.assertEqual(con.execute("PRAGMA synchronous").fetchone(), (1,))
        self.assertEqual(con.execute("PRAGMA busy_timeout").fetchone(), (5000,))
        self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone(), (1,))
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertEqual(tables, TABLES)
        self.assertTrue(indexes >= INDEXES)

    def test_reopen_preserves_rows(self):
        self.seed_ask(self.rw())
        self.assertEqual(self.rw().execute("SELECT bead,rev FROM ask").fetchall(), [("b", 0)])

    def test_concurrent_initializers_both_open_the_same_fresh_file(self):
        ready = Barrier(2, timeout=30)  # an upper bound for a loaded host, not a wait: both threads release it as they arrive
        begin = factorydb.begin_immediate

        @contextmanager
        def synchronized_begin(con):
            # Both connections already observed user_version=0 before locking.
            ready.wait()
            with begin(con):
                yield

        def open_connection():
            con = factorydb.open_rw(self.path)
            if con is None:
                self.fail("both initializers must receive a writable connection")
            try:
                tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                return con.execute("PRAGMA user_version").fetchone(), tables
            finally:
                con.close()

        with patch.object(factorydb, "begin_immediate", synchronized_begin), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: open_connection(), range(2)))
        for version, tables in results:
            self.assertEqual(version, (factorydb.SCHEMA_VERSION,))
            self.assertEqual(tables, TABLES)
        self.rw()

    def test_wrong_version_is_rejected_without_replacing_it(self):
        con = self.rw()
        con.execute("PRAGMA user_version=99")
        self.assertIsNone(factorydb.open_rw(self.path))
        self.assertIsNone(factorydb.open_ro(self.path))
        self.assertEqual(con.execute("PRAGMA user_version").fetchone(), (99,))

    def test_unversioned_nonempty_database_is_not_initialized(self):
        con = sqlite3.connect(self.path)
        self.addCleanup(con.close)
        con.execute("CREATE TABLE unrelated (value TEXT)")
        self.assertIsNone(factorydb.open_rw(self.path))
        self.assertEqual(con.execute("PRAGMA user_version").fetchone(), (0,))

    def test_corrupt_bytes_are_rejected(self):
        self.path.write_bytes(b"this is not a SQLite database")
        self.assertIsNone(factorydb.open_rw(self.path))
        self.assertIsNone(factorydb.open_ro(self.path))

    def test_non_wal_database_is_rejected(self):
        self.assertIsNone(factorydb.open_rw(":memory:"))
        con = sqlite3.connect(self.path)
        self.addCleanup(con.close)
        con.execute("PRAGMA user_version=1")
        self.assertIsNone(factorydb.open_ro(self.path))

    def test_missing_read_only_database_stays_missing(self):
        self.assertIsNone(factorydb.open_ro(self.path))
        self.assertFalse(self.path.exists())

    def test_read_only_connection_cannot_write(self):
        self.rw()
        con = self.ro()
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("INSERT INTO kv(k,v,t) VALUES ('key','value',1)")

    def test_cas_advances_once_and_rejects_stale_revision(self):
        con = self.rw()
        self.seed_ask(con)
        with factorydb.begin_immediate(con):
            self.assertTrue(factorydb.cas_update(con, "ask", "bead", "b", 0, status="answered"))
            self.assertFalse(factorydb.cas_update(con, "ask", "bead", "b", 0, status="stale"))
        self.assertEqual(con.execute("SELECT status,rev FROM ask").fetchone(), ("answered", 1))

    def test_owners_cover_exactly_the_created_tables(self):
        tables = {row[0] for row in self.rw().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(set(factorydb.OWNERS), tables)
        self.assertLessEqual(set(factorydb.OWNERS.values()), {"index", "engine", "loop", "owner"})

    def test_cas_rejects_unrevisioned_tables_and_missing_transaction(self):
        con = self.rw()
        with self.assertRaisesRegex(ValueError, "transaction"):
            factorydb.cas_update(con, "ask", "bead", "b", 0, status="answered")
        with factorydb.begin_immediate(con):
            for table in TABLES - {"run", "ask", "bead"}:
                with self.subTest(table=table), self.assertRaisesRegex(ValueError, "unrevisioned"):
                    factorydb.cas_update(con, table, "id", "key", 0)

    def test_only_revisioned_tables_are_cas_targets(self):
        con = self.rw()
        revisioned = {table for table in TABLES if "rev" in {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}}
        self.assertEqual(factorydb.REVISIONED_TABLES, revisioned)

    def test_wal_reader_keeps_snapshot_across_writer_commit(self):
        writer = self.rw()
        self.seed_ask(writer)
        reader = self.ro()
        reader.execute("BEGIN")
        self.assertEqual(reader.execute("SELECT rev FROM ask").fetchone(), (0,))
        with factorydb.begin_immediate(writer):
            self.assertTrue(factorydb.cas_update(writer, "ask", "bead", "b", 0, status="answered"))
            self.assertEqual(reader.execute("SELECT rev FROM ask").fetchone(), (0,))
        self.assertEqual(reader.execute("SELECT rev FROM ask").fetchone(), (0,))
        reader.commit()
        self.assertEqual(reader.execute("SELECT rev FROM ask").fetchone(), (1,))

    def test_transaction_rolls_back_on_exception(self):
        con = self.rw()
        with self.assertRaisesRegex(ValueError, "abort"), factorydb.begin_immediate(con):
            con.execute("INSERT INTO kv(k,v,t) VALUES ('key','value',1)")
            raise ValueError("abort")
        self.assertEqual(con.execute("SELECT * FROM kv").fetchall(), [])
        self.assertFalse(con.in_transaction)

    def test_unsafe_filesystem_is_rejected_before_connecting(self):
        with patch.object(factorydb, "_unsafe_filesystem", return_value=True):
            self.assertIsNone(factorydb.open_rw(self.path))
            self.assertIsNone(factorydb.open_ro(self.path))
        self.assertFalse(self.path.exists())

    def test_linux_mount_check_uses_deepest_mount_and_decodes_spaces(self):
        mounts = "root / ext4 rw 0 0\nremote /mnt nfs4 rw 0 0\nlocal /mnt/local\\040disk ext4 rw 0 0\n"
        with patch.object(factorydb.sys, "platform", "linux"), patch.object(Path, "read_text", return_value=mounts):
            self.assertTrue(factorydb._unsafe_filesystem(Path("/mnt/remote.db")))
            self.assertFalse(factorydb._unsafe_filesystem(Path("/mnt/local disk/factory.db")))

    def test_mount_detection_failure_prevents_connecting(self):
        with patch.object(factorydb.sys, "platform", "linux"), patch.object(Path, "read_text", side_effect=OSError):
            self.assertIsNone(factorydb._unsafe_filesystem(self.path))
            self.assertIsNone(factorydb.open_rw(self.path))
            self.assertIsNone(factorydb.open_ro(self.path))
        self.assertFalse(self.path.exists())

    def test_macos_unknown_type_rejects_mounted_parents_without_statvfs(self):
        mounted = Path("/Volumes/network")
        with (
            patch.object(factorydb.sys, "platform", "darwin"),
            patch.object(factorydb.os, "statvfs", side_effect=AssertionError("no portable filesystem type")),
            patch.object(factorydb.os.path, "ismount", side_effect=lambda path: path in {Path("/"), mounted}),
        ):
            self.assertEqual(factorydb._filesystem_type(self.path), "unknown")
            self.assertTrue(factorydb._unsafe_filesystem(mounted / "nested/factory.db"))
            self.assertFalse(factorydb._unsafe_filesystem(Path("/Users/local/factory.db")))

    def test_unknown_mount_probe_failure_prevents_connecting(self):
        with (
            patch.object(factorydb, "_filesystem_type", return_value="unknown"),
            patch.object(factorydb.os.path, "ismount", side_effect=OSError),
        ):
            self.assertIsNone(factorydb.open_rw(self.path))

    def test_schema_creation_failure_leaves_no_partial_schema(self):
        with patch.object(factorydb, "DDL", factorydb.DDL + "\nINVALID SQL;"):
            self.assertIsNone(factorydb.open_rw(self.path))
        con = sqlite3.connect(self.path)
        self.addCleanup(con.close)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone(), (0,))
        self.assertEqual(con.execute("SELECT name FROM sqlite_master").fetchall(), [])

    def test_failed_quick_check_is_rejected(self):
        class BadCheckConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql == "PRAGMA quick_check":
                    return super().execute("SELECT 'damaged'")
                return super().execute(sql, parameters)

        connect = sqlite3.connect

        def bad_connection(*args, **kwargs):
            return connect(*args, factory=BadCheckConnection, **kwargs)

        with patch.object(factorydb.sqlite3, "connect", side_effect=bad_connection):
            self.assertIsNone(factorydb.open_rw(self.path))
        factorydb._CHECKED.clear()
        with patch.object(factorydb.sqlite3, "connect", side_effect=bad_connection):
            self.assertIsNone(factorydb.open_rw(self.path))

    def test_run_has_no_family_authority_or_writer_column(self):
        con = self.rw()
        self.assertEqual(con.execute("SELECT name FROM sqlite_master WHERE name='family'").fetchall(), [])
        columns = {r[1]: r for r in con.execute("PRAGMA table_info(run)")}
        self.assertNotIn("writer", columns)
        self.assertEqual(columns["manifest"][3], 1)

    def test_bead_projection_is_index_owned_and_revisioned(self):
        con = self.rw()
        self.assertEqual(factorydb.OWNERS["bead"], "index")
        self.assertEqual(con.execute("PRAGMA foreign_key_list(bead)").fetchall(), [])
        con.execute("INSERT INTO bead(id,repo_key,status,updated,fetched) VALUES ('opaque.id','repo','open',1,2)")
        self.assertEqual(
            con.execute("SELECT title,priority,type,parent,assignee,labels,rev FROM bead").fetchone(),
            ("", None, "", "", "", "[]", 0),
        )
        with factorydb.begin_immediate(con):
            self.assertTrue(factorydb.cas_update(con, "bead", "id", "opaque.id", 0, parent="unrelated", status="closed"))
            self.assertFalse(factorydb.cas_update(con, "bead", "id", "opaque.id", 0, status="stale"))
        self.assertEqual(con.execute("SELECT parent,status,rev FROM bead").fetchone(), ("unrelated", "closed", 1))

    def test_change_counter_observes_only_other_connection_commits(self):
        writer = self.rw()
        reader = self.ro()
        before_reader = factorydb.change_counter(reader)
        before_writer = factorydb.change_counter(writer)
        self.assertIsInstance(before_reader, int)
        with factorydb.begin_immediate(writer):
            writer.execute("INSERT INTO kv(k,v,t) VALUES ('key','value',1)")
            self.assertEqual(factorydb.change_counter(reader), before_reader)
        after_reader = factorydb.change_counter(reader)
        self.assertNotEqual(after_reader, before_reader)
        self.assertEqual(factorydb.change_counter(writer), before_writer)
        self.assertEqual(factorydb.change_counter(reader), after_reader)
        with self.assertRaises(ValueError), factorydb.begin_immediate(writer):
            writer.execute("UPDATE kv SET v='rolled back'")
            raise ValueError("abort")
        self.assertEqual(factorydb.change_counter(reader), after_reader)

    def seed_history(self, con, run="old", state="done", ended=2):
        con.execute(
            "INSERT INTO run(run,repo,repo_key,bead,state,started,ended,manifest) VALUES (?,'repo','repo',?,?,1,?,'{}')",
            (run, run, state, ended),
        )
        con.execute("INSERT INTO attempt(run,n,started,ended) VALUES (?,1,1,2)", (run,))
        con.execute("INSERT INTO step(run,key,try,attempt,status,started,ended) VALUES (?,'s',1,1,'ok',1,2)", (run,))
        con.execute("INSERT INTO effect(key,run,name,state,intent_at,done_at) VALUES (?,?,'e','done',1,2)", (run, run))
        con.execute("INSERT INTO check_round(run,round,ts,body) VALUES (?,1,2,'{}')", (run,))

    def test_prune_deletes_old_finished_history_and_returns_counts(self):
        con = self.rw()
        self.seed_history(con)
        con.execute("INSERT INTO ask(bead,id,status,t,body) VALUES ('old','a','answered',1,'{}')")
        con.execute("INSERT INTO ask_ledger(t,event,ask,bead,body,origin) VALUES (2,'answer','a','old','{}','o')")
        con.execute("INSERT INTO ask_ledger(t,event,body,origin) VALUES (10,'answer','{}','recent')")
        counts = factorydb.prune_older_than(con, 10)
        self.assertEqual(counts, dict.fromkeys(("ask_ledger", "check_round", "step", "attempt", "effect", "run"), 1))
        self.assertEqual(con.execute("SELECT origin FROM ask_ledger").fetchall(), [("recent",)])
        self.assertEqual(con.execute("SELECT status FROM ask").fetchall(), [("answered",)])
        self.assertFalse(con.in_transaction)
        self.assertTrue(all(count == 0 for count in factorydb.prune_older_than(con, 10).values()))

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
        self.assertTrue(all(count == 0 for count in factorydb.prune_older_than(con, 10).values()))
        for table in ("run", "attempt", "step", "effect", "check_round"):
            self.assertEqual(con.execute(f'SELECT count(*) FROM "{table}"').fetchone(), (9,))
        for table in ("lease", "wait", "signal"):
            self.assertEqual(con.execute(f'SELECT count(*) FROM "{table}"').fetchone(), (1,))
        self.assertEqual(con.execute("SELECT count(*) FROM ask").fetchone(), (2,))

    def test_prune_keeps_open_ask_and_running_run_audit(self):
        con = self.rw()
        self.seed_history(con, "running", "running")
        self.seed_ask(con)
        for bead in ("running", "b"):
            con.execute("INSERT INTO ask_ledger(t,event,bead,body,origin) VALUES (1,'state',?,'{}',?)", (bead, bead))
        self.assertTrue(all(count == 0 for count in factorydb.prune_older_than(con, 10).values()))
        self.assertEqual(con.execute("SELECT count(*) FROM ask_ledger").fetchone(), (2,))

    def test_prune_consumed_signal_does_not_pin_history(self):
        con = self.rw()
        self.seed_history(con)
        con.execute("INSERT INTO signal(run,kind,at,taken) VALUES ('old','stop',1,2)")
        self.assertEqual(factorydb.prune_older_than(con, 10)["run"], 1)
        self.assertEqual(con.execute("SELECT taken FROM signal").fetchall(), [(2.0,)])

    def test_prune_standalone_gate_rounds_by_timestamp(self):
        con = self.rw()
        for number, ts in ((1, 2), (2, 10), (3, None)):
            con.execute("INSERT INTO check_round(run,round,ts,body) VALUES ('standalone',?,?,'{}')", (number, ts))
        self.assertEqual(factorydb.prune_older_than(con, 10, ("check_round",)), {"check_round": 1})
        self.assertEqual(con.execute("SELECT round FROM check_round ORDER BY round").fetchall(), [(2,), (3,)])

    def test_prune_subset_keeps_parent_until_all_children_are_removed(self):
        con = self.rw()
        self.seed_history(con)
        self.assertEqual(factorydb.prune_older_than(con, 10, ("run",)), {"run": 0})
        self.assertEqual(factorydb.prune_older_than(con, 10, ("step", "run")), {"step": 1, "run": 0})
        self.assertEqual(
            factorydb.prune_older_than(con, 10, ("attempt", "effect", "check_round", "run")),
            {"check_round": 1, "attempt": 1, "effect": 1, "run": 1},
        )

    def test_prune_rejects_state_tables_before_deleting_anything(self):
        con = self.rw()
        self.seed_history(con)
        for table in TABLES - {"ask_ledger", "check_round", "step", "attempt", "effect", "run"}:
            with self.subTest(table=table), self.assertRaisesRegex(ValueError, "history"):
                factorydb.prune_older_than(con, 10, ("step", table))
        self.assertEqual(con.execute("SELECT count(*) FROM step").fetchone(), (1,))

    def test_prune_rolls_back_all_deletes_if_parent_delete_fails(self):
        con = self.rw()
        self.seed_history(con)
        con.execute("CREATE TRIGGER retain_run BEFORE DELETE ON run BEGIN SELECT RAISE(ABORT,'retain'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "retain"):
            factorydb.prune_older_than(con, 10)
        for table in ("run", "attempt", "step", "effect", "check_round"):
            self.assertEqual(con.execute(f'SELECT count(*) FROM "{table}"').fetchone(), (1,))
        self.assertFalse(con.in_transaction)

    def test_quick_check_creation_once_per_writable_process_and_version_mismatch(self):
        checks = []

        class CountingConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql == "PRAGMA quick_check":
                    checks.append(sql)
                return super().execute(sql, parameters)

        connect = sqlite3.connect

        def counted_connection(*args, **kwargs):
            return connect(*args, factory=CountingConnection, **kwargs)

        with patch.object(factorydb.sqlite3, "connect", side_effect=counted_connection):
            con = self.rw()
            self.rw()
            self.ro()
            self.assertEqual(len(checks), 1)
            factorydb._CHECKED.clear()  # Simulate the first writable open in another process.
            self.ro()
            self.assertEqual(len(checks), 1)
            self.rw()
            self.rw()
            self.assertEqual(len(checks), 2)
            con.execute("PRAGMA user_version=99")
            self.assertIsNone(factorydb.open_rw(self.path))
            self.assertIsNone(factorydb.open_ro(self.path))
            self.assertEqual(len(checks), 4)


if __name__ == "__main__":
    unittest.main()
