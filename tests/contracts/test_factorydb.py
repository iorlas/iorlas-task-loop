"""Shared writer identity, ownership, cleanup and short transaction guarantees."""

import os
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import support.paths  # noqa: F401
from support.narrow import must

from taskloop.contracts import factorydb
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest
from taskloop.contracts.runrows import RunRows


class SharedWriterTest(unittest.TestCase):
    def setUp(self):
        factorydb.close_shared()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(factorydb.close_shared)
        self.cfg = ConfigDir(Path(tmp.name))
        self.path = self.cfg.factory_db()

    def shared(self):
        return must(factorydb.shared_rw(self.path))

    def assert_closed(self, con):
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")

    def test_calls_and_resolved_aliases_reuse_the_same_connection(self):
        con = self.shared()
        alias = self.path.parent / "alias"
        alias.symlink_to(self.path.parent, target_is_directory=True)
        self.assertIs(self.shared(), con)
        self.assertIs(factorydb.shared_rw(alias / self.path.name), con)
        self.assertFalse(con.in_transaction)

    def test_deleted_file_closes_stale_writer_and_creates_a_new_database(self):
        con = self.shared()
        con.execute("INSERT INTO kv(k,v,t) VALUES ('old','value',1)")
        self.path.unlink()
        fresh = self.shared()
        self.assertIsNot(fresh, con)
        self.assert_closed(con)
        self.assertEqual(fresh.execute("SELECT * FROM kv").fetchall(), [])

    def test_replaced_file_is_reopened_with_its_own_contents(self):
        con = self.shared()
        replacement = self.path.with_name("replacement.db")
        other = must(factorydb.open_rw(replacement))
        try:
            other.execute("INSERT INTO kv(k,v,t) VALUES ('new','value',1)")
        finally:
            other.close()
        for suffix in ("", "-wal", "-shm"):  # a replacement moves the sidecars with the file, as the v1 quarantine does
            self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)
        replacement.rename(self.path)
        fresh = self.shared()
        self.assertIsNot(fresh, con)
        self.assert_closed(con)
        self.assertEqual(fresh.execute("SELECT k FROM kv").fetchall(), [("new",)])

    def test_other_thread_gets_its_own_writer_and_cleanup_closes_both(self):
        con = self.shared()

        def in_thread():
            first = self.shared()
            self.assertIs(first, self.shared())
            return first

        with ThreadPoolExecutor(max_workers=1) as pool:
            other = pool.submit(in_thread).result()
        self.assertIsNot(other, con)
        factorydb.close_shared()
        self.assert_closed(con)
        self.assert_closed(other)
        self.assertIsNot(self.shared(), con)

    def test_pid_change_gets_a_new_writer_and_cleanup_only_closes_that_process(self):
        con = self.shared()
        pid = os.getpid()
        with patch.object(factorydb.os, "getpid", return_value=pid + 1):
            child = self.shared()
            self.assertIsNot(child, con)
            self.assertIs(self.shared(), child)
            factorydb.close_shared()
            self.assert_closed(child)
            self.assertEqual(con.execute("SELECT 1").fetchone(), (1,))
        self.assertIs(self.shared(), con)

    def test_closed_and_unfinished_connections_are_replaced(self):
        con = self.shared()
        con.close()
        fresh = self.shared()
        self.assertIsNot(fresh, con)
        fresh.execute("BEGIN IMMEDIATE")
        fresh.execute("INSERT INTO kv(k,v,t) VALUES ('rollback','value',1)")
        clean = self.shared()
        self.assertIsNot(clean, fresh)
        self.assert_closed(fresh)
        self.assertFalse(clean.in_transaction)
        self.assertEqual(clean.execute("SELECT * FROM kv").fetchall(), [])

    def test_database_errors_evict_the_writer_and_roll_back_changes(self):
        for error in (sqlite3.DatabaseError("corrupt"), sqlite3.OperationalError("database disk image is malformed")):
            with self.subTest(error=error):
                con = self.shared()
                with self.assertRaises(type(error)), factorydb.begin_immediate(con):
                    con.execute("INSERT INTO kv(k,v,t) VALUES ('rollback','value',1)")
                    raise error
                self.assert_closed(con)
                fresh = self.shared()
                self.assertIsNot(fresh, con)
                self.assertEqual(fresh.execute("SELECT * FROM kv").fetchall(), [])

    def test_begin_failure_evicts_the_writer(self):
        con = self.shared()
        con.execute("BEGIN IMMEDIATE")
        with self.assertRaises(sqlite3.OperationalError), factorydb.begin_immediate(con):
            self.fail("a nested transaction must not begin")
        self.assert_closed(con)
        self.assertFalse(self.shared().in_transaction)

    def test_commit_failure_evicts_the_writer_and_rolls_back(self):
        class BrokenCommit(sqlite3.Connection):
            def commit(self):
                raise sqlite3.DatabaseError("commit failed")

        initializer = must(factorydb.open_rw(self.path))
        initializer.close()
        connect = sqlite3.connect

        def broken_connection(*args, **kwargs):
            return connect(*args, factory=BrokenCommit, **kwargs)

        with patch.object(factorydb.sqlite3, "connect", side_effect=broken_connection):
            con = self.shared()
            with self.assertRaisesRegex(sqlite3.DatabaseError, "commit failed"), factorydb.begin_immediate(con):
                con.execute("INSERT INTO kv(k,v,t) VALUES ('rollback','value',1)")
        self.assert_closed(con)
        self.assertEqual(self.shared().execute("SELECT * FROM kv").fetchall(), [])

    def test_runrows_commit_and_rollback_keep_writer_idle_and_changes_atomic(self):
        rows = RunRows(self.cfg)
        manifest = RunManifest(run="r", repo="/repo", bead="b", started=1.0)
        rows.put(manifest)
        con = self.shared()
        self.assertFalse(con.in_transaction)
        with self.assertRaisesRegex(ValueError, "abort"), rows.transaction() as writer:
            self.assertIs(writer, con)
            rows.write(writer, manifest.replace(owner="rolled back"))
            raise ValueError("abort")
        self.assertFalse(con.in_transaction)
        self.assertIs(self.shared(), con)
        self.assertEqual(rows.get("r"), manifest)
        reader = must(factorydb.open_ro(self.path))
        try:
            self.assertEqual(reader.execute("SELECT count(*) FROM run").fetchone(), (1,))
        finally:
            reader.close()

    def test_200_runrows_put_get_cycles_under_half_a_second(self):
        rows = RunRows(self.cfg)
        manifest = RunManifest(run="r", repo="/repo", bead="b", started=1.0)
        started = time.perf_counter()
        for _ in range(200):
            rows.put(manifest)
            self.assertEqual(rows.get("r"), manifest)
        self.assertLess(time.perf_counter() - started, 0.5)
