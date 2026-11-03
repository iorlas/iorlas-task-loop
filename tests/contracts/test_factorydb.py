"""Factory schema, fallback conditions and WAL transaction guarantees."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import factorydb

TABLES = {
    "family", "source", "run", "attempt", "step", "lease", "event", "check_pass",
    "check_round", "ask", "ask_ledger", "kv", "effect", "wait", "signal",
}
INDEXES = {
    "run_bead", "run_recent", "run_live", "event_t", "event_run", "event_bead",
    "event_repo", "check_tree", "ask_live",
}


class FactoryDbTest(unittest.TestCase):
    def setUp(self):
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
        self.assertEqual(con.execute("PRAGMA user_version").fetchone(), (1,))
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

    def test_wrong_version_falls_back_without_replacing_it(self):
        con = self.rw()
        con.execute("PRAGMA user_version=2")
        self.assertIsNone(factorydb.open_rw(self.path))
        self.assertIsNone(factorydb.open_ro(self.path))
        self.assertEqual(con.execute("PRAGMA user_version").fetchone(), (2,))

    def test_unversioned_nonempty_database_is_not_initialized(self):
        con = sqlite3.connect(self.path)
        self.addCleanup(con.close)
        con.execute("CREATE TABLE unrelated (value TEXT)")
        self.assertIsNone(factorydb.open_rw(self.path))
        self.assertEqual(con.execute("PRAGMA user_version").fetchone(), (0,))

    def test_corrupt_bytes_fall_back(self):
        self.path.write_bytes(b"this is not a SQLite database")
        self.assertIsNone(factorydb.open_rw(self.path))
        self.assertIsNone(factorydb.open_ro(self.path))

    def test_non_wal_database_falls_back(self):
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
        self.assertLessEqual(set(factorydb.OWNERS.values()), {"index", "engine", "loop", "owner", "any:cas"})

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

    def test_unsafe_filesystem_falls_back_before_connecting(self):
        with patch.object(factorydb, "_unsafe_filesystem", return_value=True):
            self.assertIsNone(factorydb.open_rw(self.path))
            self.assertIsNone(factorydb.open_ro(self.path))
        self.assertFalse(self.path.exists())

    def test_linux_mount_check_uses_deepest_mount_and_decodes_spaces(self):
        mounts = "root / ext4 rw 0 0\nremote /mnt nfs4 rw 0 0\nlocal /mnt/local\\040disk ext4 rw 0 0\n"
        with patch.object(factorydb.sys, "platform", "linux"), patch.object(Path, "read_text", return_value=mounts):
            self.assertTrue(factorydb._unsafe_filesystem(Path("/mnt/remote.db")))
            self.assertFalse(factorydb._unsafe_filesystem(Path("/mnt/local disk/factory.db")))

    def test_mount_detection_failure_is_harmless(self):
        with patch.object(factorydb.sys, "platform", "linux"), patch.object(Path, "read_text", side_effect=OSError):
            self.assertFalse(factorydb._unsafe_filesystem(self.path))

    def test_schema_creation_failure_leaves_no_partial_schema(self):
        with patch.object(factorydb, "DDL", factorydb.DDL + "\nINVALID SQL;"):
            self.assertIsNone(factorydb.open_rw(self.path))
        con = sqlite3.connect(self.path)
        self.addCleanup(con.close)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone(), (0,))
        self.assertEqual(con.execute("SELECT name FROM sqlite_master").fetchall(), [])

    def test_failed_quick_check_falls_back(self):
        class BadCheckConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql == "PRAGMA quick_check":
                    return super().execute("SELECT 'damaged'")
                return super().execute(sql, parameters)

        self.rw()
        connect = sqlite3.connect

        def bad_connection(*args, **kwargs):
            return connect(*args, factory=BadCheckConnection, **kwargs)

        with patch.object(factorydb.sqlite3, "connect", side_effect=bad_connection):
            self.assertIsNone(factorydb.open_rw(self.path))
            self.assertIsNone(factorydb.open_ro(self.path))


if __name__ == "__main__":
    unittest.main()
