"""Factory upgrades preserve authoritative rows and serialize concurrent openers."""

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import support.paths  # noqa: F401
from support.narrow import must

from taskloop.contracts import factorydb, factorymigrate


def add_summary(con: sqlite3.Connection) -> None:
    con.execute("ALTER TABLE run ADD COLUMN summary TEXT")
    con.execute("UPDATE run SET summary=state || ':' || bead")


class FactoryMigrateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "factory.db"
        self.con = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.con.close)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript(factorydb.DDL)
        self.con.execute("PRAGMA user_version=2")
        self.con.execute(
            "INSERT INTO run(run,repo,repo_key,bead,state,started,manifest) "
            "VALUES ('r','/repo','repo','b','running',1,'{}')")
        self.con.execute("INSERT INTO attempt(run,n,started) VALUES ('r',1,2)")
        self.con.execute("INSERT INTO step(run,key,try,attempt,status,started) VALUES ('r','build',1,1,'done',3)")
        self.old_rows = self.rows()

    def rows(self):
        return {table: self.con.execute(f"SELECT * FROM {table}").fetchall() for table in ("run", "attempt", "step")}

    def assert_original_rows(self):
        for table, rows in self.old_rows.items():
            columns = len(rows[0])
            actual = [row[:columns] for row in self.con.execute(f"SELECT * FROM {table}")]
            self.assertEqual(actual, rows)

    def test_add_column_and_backfill_preserve_all_authoritative_rows(self):
        identity = self.path.stat().st_ino
        factorymigrate.upgrade(self.con, {2: add_summary}, 2, 3)
        self.assert_original_rows()
        self.assertEqual(self.con.execute("SELECT summary FROM run").fetchall(), [("running:b",)])
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone(), (3,))
        self.assertEqual(self.path.stat().st_ino, identity)
        self.assertFalse(self.con.in_transaction)

    def test_steps_run_in_order_and_see_the_preceding_version(self):
        observed = []

        def next_step(con):
            observed.append(con.execute("PRAGMA user_version").fetchone()[0])
            con.execute("UPDATE run SET summary=summary || ':upgraded'")

        factorymigrate.upgrade(self.con, {2: add_summary, 3: next_step}, 2, 4)
        self.assertEqual(observed, [3])
        self.assertEqual(self.con.execute("SELECT summary FROM run").fetchone(), ("running:b:upgraded",))
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone(), (4,))
        self.assert_original_rows()

    def test_failing_step_rolls_back_the_entire_chain_including_ddl(self):
        def fail(con):
            con.execute("UPDATE attempt SET started=999")
            raise ValueError("backfill failed")

        with self.assertRaisesRegex(factorydb.DatabaseError, "step v3 -> v4 failed: backfill failed"):
            factorymigrate.upgrade(self.con, {2: add_summary, 3: fail}, 2, 4)
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone(), (2,))
        self.assertEqual(self.rows(), self.old_rows)
        self.assertNotIn("summary", [row[1] for row in self.con.execute("PRAGMA table_info(run)")])
        self.assertFalse(self.con.in_transaction)

    def test_missing_step_names_the_gap_and_rolls_back_prior_steps(self):
        with self.assertRaisesRegex(factorydb.DatabaseError, "missing upgrade step v3 -> v4"):
            factorymigrate.upgrade(self.con, {2: add_summary}, 2, 4)
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone(), (2,))
        self.assertEqual(self.rows(), self.old_rows)
        self.assertFalse(self.con.in_transaction)

    def test_two_concurrent_upgraders_apply_step_exactly_once(self):
        ready = Barrier(2, timeout=5)
        calls = []

        def step(con):
            calls.append(1)
            add_summary(con)

        def opener():
            con = sqlite3.connect(self.path, isolation_level=None, timeout=5)
            try:
                current = con.execute("PRAGMA user_version").fetchone()[0]
                ready.wait()
                factorymigrate.upgrade(con, {2: step}, current, 3)
                return con.execute("PRAGMA user_version").fetchone()[0]
            finally:
                con.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(opener)
            second = pool.submit(opener)
            versions = [first.result(), second.result()]
        self.assertEqual(calls, [1])
        self.assertEqual(versions, [3, 3])
        self.assert_original_rows()

    def test_already_upgraded_connection_needs_no_steps(self):
        factorymigrate.upgrade(self.con, {2: add_summary}, 2, 3)
        factorymigrate.upgrade(self.con, {}, 2, 3)
        self.assert_original_rows()
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone(), (3,))

    def test_upgrade_refuses_a_version_newer_than_target(self):
        self.con.execute("PRAGMA user_version=4")
        with self.assertRaisesRegex(factorydb.DatabaseError, "schema v4.*knows v3.*update task-loop"):
            factorymigrate.upgrade(self.con, {}, 2, 3)
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone(), (4,))
        self.assertEqual(self.rows(), self.old_rows)

    def test_newer_schema_refuses_both_opens_without_quarantine_or_checks(self):
        found = factorydb.SCHEMA_VERSION + 1
        self.con.execute(f"PRAGMA user_version={found}")
        message = f"schema v{found}.*knows v{factorydb.SCHEMA_VERSION}.*update task-loop"
        with patch.object(factorydb, "_check_integrity", side_effect=AssertionError("unexpected integrity check")):
            for opener in (factorydb.open_rw, factorydb.open_ro):
                with self.subTest(opener=opener.__name__), self.assertRaisesRegex(factorydb.DatabaseError, message):
                    opener(self.path)
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone(), (found,))
        self.assertEqual(self.rows(), self.old_rows)
        self.assertEqual(list(self.path.parent.glob("factory.db.bad-*")), [])

    def test_older_reader_refuses_then_writer_upgrades_in_place(self):
        identity = self.path.stat().st_ino
        with patch.object(factorydb, "SCHEMA_VERSION", 3), patch.object(factorymigrate, "STEPS", {2: add_summary}):
            with self.assertRaisesRegex(factorydb.DatabaseError, "schema v2.*knows v3.*engine has not upgraded it yet"):
                factorydb.open_ro(self.path)
            self.assertEqual(self.con.execute("PRAGMA user_version").fetchone(), (2,))
            writer = must(factorydb.open_rw(self.path))
            writer.close()
            reader = must(factorydb.open_ro(self.path))
            try:
                self.assertEqual(reader.execute("SELECT summary FROM run").fetchone(), ("running:b",))
            finally:
                reader.close()
        self.assertEqual(self.path.stat().st_ino, identity)
        self.assert_original_rows()
        self.assertEqual(list(self.path.parent.glob("factory.db.bad-*")), [])

    def test_writer_reports_upgrade_failure_without_quarantine(self):
        with patch.object(factorydb, "SCHEMA_VERSION", 3), \
                self.assertRaisesRegex(factorydb.DatabaseError, "missing upgrade step v2 -> v3"):
            factorydb.open_rw(self.path)
        self.assertEqual(self.con.execute("PRAGMA user_version").fetchone(), (2,))
        self.assertEqual(self.rows(), self.old_rows)
        self.assertEqual(list(self.path.parent.glob("factory.db.bad-*")), [])
