"""Authoritative run wire records, revisions, legacy import and schema retirement."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import support.paths  # noqa: F401
from support.narrow import must

from taskloop.contracts import factorydb, wire
from taskloop.contracts.enums import Outcome, Result, Step, WhyCode
from taskloop.contracts.ids import loop_key
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunFinish, RunManifest, RunState
from taskloop.contracts.runrows import RunRows, StaleRevision, import_legacy
from taskloop.contracts.stores import JsonStore


class RunRowsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.rows = RunRows(self.cfg)

    def complete(self):
        finish = RunFinish(state=RunState.DONE, ended=20.0, outcome=Outcome.DONE, result=Result.LANDED,
                           kind="landed", why="delivered", sha="abc", why_code=WhyCode.VERIFY, end='{"payload":"retained"}')
        return RunManifest(run="r", repo="/repo", bead="b", started=10.0, ended=20.0, loop="loop", attempts=4,
                           state=RunState.DONE, heartbeat=20.0, pid=123, host="host", reason="delivered", mode="stage:gate",
                           owner="ownér", session="session", beads=("b2", "b3"), next_step=Step.GATE, worktree="/tree",
                           branch="feature", sha="abc", finish=finish, finish_projected=True)

    def test_roundtrip_every_manifest_field_and_matching_relational_columns(self):
        m = self.complete()
        self.rows.put(m)
        self.assertEqual(self.rows.get(m.run), m)
        assert m.finish is not None and m.next_step is not None
        with self.rows.transaction() as con:
            row = con.execute("SELECT repo,repo_key,bead,mode,owner,session,loop,worktree,branch,sha,state,reason,"
                              "started,ended,next_step,outcome,why,manifest,rev FROM run").fetchone()
        self.assertEqual(row[:17], (m.repo, loop_key(m.repo), m.bead, m.mode, m.owner, m.session, m.loop, m.worktree,
                                    m.branch, m.sha, m.state.value, m.reason, m.started, m.ended, m.next_step.value,
                                    m.finish.outcome.value, m.finish.why))
        self.assertEqual(row[17:], (json.dumps(wire.dump(m), indent=1, ensure_ascii=False) + "\n", 0))
        self.rows.put(m.replace(repo="/new", bead="new", state=RunState.FAILED), expect_rev=0)
        with self.rows.transaction() as con:
            self.assertEqual(con.execute("SELECT repo,repo_key,bead,state,rev FROM run").fetchone(),
                             ("/new", loop_key("/new"), "new", "failed", 1))

    def test_stale_revision_and_failed_change_leave_the_row_unchanged(self):
        m = self.complete()
        self.rows.put(m)
        self.rows.put(m.replace(owner="new"), expect_rev=0)
        before = self.rows.snapshot(m.run)
        with self.assertRaises(StaleRevision):
            self.rows.put(m, expect_rev=0)
        with self.assertRaises(StaleRevision):
            self.rows.put(m.replace(run="missing"), expect_rev=0)
        self.assertEqual(self.rows.snapshot(m.run), before)
        with self.assertRaisesRegex(ValueError, "abort"), self.rows.transaction() as con:
            self.rows.write(con, m)
            raise ValueError("abort")
        self.assertEqual(self.rows.snapshot(m.run), before)

    def test_queries_are_ordered_and_filter_in_sql(self):
        for run, repo, bead, started in (("z", "/r", "b", 2.0), ("b", "/r", "c", 1.0), ("a", "/s", "b", 1.0)):
            self.rows.put(RunManifest(run=run, repo=repo, bead=bead, started=started))
        self.assertEqual([m.run for m in self.rows.all()], ["a", "b", "z"])
        self.assertEqual([m.run for m in self.rows.of_bead("b")], ["a", "z"])
        self.assertEqual([m.run for m in self.rows.of_bead("b", "/r")], ["z"])
        self.assertEqual([m.run for m in self.rows.of_repo("/r")], ["b", "z"])

    def legacy(self, m):
        JsonStore(self.cfg.run_manifest(m.run), RunManifest).write(m)

    def test_import_is_insert_only_repeatable_and_preserves_legacy_bytes(self):
        for run in ("a", "b", "c"):
            self.legacy(self.complete().replace(run=run))
        torn = self.cfg.run_manifest("torn")
        torn.parent.mkdir(parents=True)
        torn.write_text("{")
        files = {p: p.read_bytes() for p in self.cfg.runs_dir().glob("*/manifest.json")}
        self.assertEqual(import_legacy(self.cfg), 3)
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        before = self.rows.snapshot("a")
        self.legacy(self.complete().replace(run="a", owner="stale file"))
        self.assertEqual(import_legacy(self.cfg), 0)
        self.assertEqual(self.rows.snapshot("a"), before)
        for path, raw in files.items():
            if path.parent.name != "a":
                self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(must(JsonStore(self.cfg.run_manifest("a"), RunManifest).get()).owner, "stale file")

    def test_locator_imports_only_once_and_never_rereads_an_imported_file(self):
        self.legacy(self.complete())
        first = RunLocator(self.cfg)
        self.assertEqual(must(first.get("r")).manifest, self.complete())
        self.cfg.run_manifest("r").write_text("{")
        with patch.object(Path, "iterdir", side_effect=AssertionError("repeated directory scan")), \
                patch.object(JsonStore, "get", side_effect=AssertionError("legacy reread")):
            self.assertEqual(RunLocator(self.cfg).runs(), first.runs())
            self.assertEqual(must(first.get("r")).manifest, self.complete())

    def test_import_skips_a_manifest_under_another_run_id(self):
        path = self.cfg.run_manifest("wrong")
        JsonStore(path, RunManifest).write(self.complete())
        before = path.read_bytes()
        self.assertEqual(import_legacy(self.cfg), 0)
        self.assertEqual(self.rows.all(), [])
        self.assertEqual(path.read_bytes(), before)

    def test_v1_is_moved_aside_and_v2_created_with_one_warning(self):
        path = self.cfg.factory_db()
        with sqlite3.connect(path) as con:
            con.execute("CREATE TABLE derived (value TEXT)")
            con.execute("INSERT INTO derived VALUES ('old projection')")
            con.execute("PRAGMA user_version=1")
        con.close()
        with self.assertLogs("taskloop.contracts.factorydb", level="WARNING") as logs:
            con = factorydb.open_rw(path)
        assert con is not None
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone(), (2,))
            self.assertEqual(con.execute("SELECT count(*) FROM run").fetchone(), (0,))
        finally:
            con.close()
        bad, = self.cfg.root.glob("factory.db.bad-*")
        with sqlite3.connect(bad) as old:
            self.assertEqual(old.execute("SELECT * FROM derived").fetchall(), [("old projection",)])
        old.close()
        self.assertEqual(len(logs.output), 1)

    def test_corruption_is_an_error_and_never_reads_legacy(self):
        self.legacy(self.complete())
        self.cfg.factory_db().write_bytes(b"broken database")
        with patch.object(JsonStore, "get", side_effect=AssertionError("file fallback")), \
                self.assertRaises(factorydb.DatabaseError):
            RunLocator(self.cfg).get("r")
        self.assertEqual(self.cfg.factory_db().read_bytes(), b"broken database")

    def test_unreadable_manifest_row_is_an_error_without_a_legacy_read(self):
        self.legacy(self.complete())
        import_legacy(self.cfg)
        with self.rows.transaction() as con:
            con.execute("UPDATE run SET manifest='{' WHERE run='r'")
        with patch.object(JsonStore, "get", side_effect=AssertionError("file fallback")):
            with self.assertRaises(factorydb.DatabaseError):
                self.rows.get("r")
            with self.assertRaises(factorydb.DatabaseError):
                self.rows.all()
