"""Durable run indexing: crash replay, source identity, ownership and one read path."""

import builtins
import json
import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support.dashlogs import RunScript, T
from support.narrow import must
from support.runs import manifest

from dash import test_dash_api as fixtures
from taskloop.contracts import factorydb
from taskloop.contracts.ids import loop_key
from taskloop.contracts.paths import ConfigDir
from taskloop_dash.app import Dash
from taskloop_dash.env import Env
from taskloop_dash.index import Indexer, reindex

NOW = T + 3600


class FactoryIndex(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.paths = []
        for i in range(12):
            script = RunScript(f"b-{i}", at=i).step("plan", 2, i + 1)
            for _ in range(i):
                script.step("write", 3, 7)
            script.close("done").write(self.cfg.root)
            path = self.cfg.engine_log(script.name)
            with path.open("ab") as file:
                file.write(b'{"v":3,"kind":"beat"')
            os.utime(path, (NOW, NOW))
            self.paths.append(path)

    def rows(self):
        con = must(factorydb.open_ro(self.cfg.factory_db()))
        try:
            return con.execute("SELECT run, facts, facts_upto FROM run ORDER BY run").fetchall()
        finally:
            con.close()

    def sources(self):
        con = must(factorydb.open_ro(self.cfg.factory_db()))
        try:
            return con.execute("SELECT * FROM source ORDER BY path").fetchall()
        finally:
            con.close()

    def ingest(self, **kw):
        with Indexer(self.cfg, clock=lambda: NOW, **kw) as index:
            while not index.pass_once(budget=0.2):
                pass

    def check_interruptions(self, seeds):
        reindex(self.cfg, clock=lambda: NOW)
        expected = self.rows()
        expected_sources = self.sources()
        for seed in seeds:
            rng = random.Random(seed)
            remaining = [rng.randrange(1, 250)]

            def interrupt(_record, remaining=remaining):
                remaining[0] -= 1
                if remaining[0] == 0:
                    raise InterruptedError("simulated kill during a transaction")

            with self.subTest(seed=seed):
                with Indexer(self.cfg, clock=lambda: NOW, on_record=interrupt) as index:
                    index.clear()
                    try:
                        while not index.pass_once():
                            pass
                    except InterruptedError:
                        pass
                self.ingest()
                self.assertEqual(self.rows(), expected)
                self.assertEqual(self.sources(), expected_sources)

    def test_interruptions_seeds_0_to_7(self):
        self.check_interruptions(range(8))

    def test_interruptions_seeds_8_to_15(self):
        self.check_interruptions(range(8, 16))

    def test_interruptions_seeds_16_to_23(self):
        self.check_interruptions(range(16, 24))

    def test_interruptions_seeds_24_to_31(self):
        self.check_interruptions(range(24, 32))

    def test_rotation_same_inode_replacement_truncation_and_deletion(self):
        self.ingest()
        path = self.paths[-1]
        original = path.read_bytes()
        replacement = original.replace(b'"plan"', b'"read"')
        for kind in ("rotate", "replace", "truncate", "delete"):
            with self.subTest(kind=kind):
                if kind == "rotate":
                    other = path.with_suffix(".new")
                    other.write_bytes(replacement)
                    other.replace(path)
                elif kind == "replace":
                    inode = path.stat().st_ino
                    path.write_bytes(original)
                    self.assertEqual(path.stat().st_ino, inode)
                elif kind == "truncate":
                    path.write_bytes(original.splitlines(keepends=True)[0])
                else:
                    path.unlink()
                self.ingest()
                incremental = self.rows()
                reindex(self.cfg, clock=lambda: NOW)
                self.assertEqual(self.rows(), incremental)

    def test_restart_parses_only_appended_complete_lines(self):
        self.ingest()
        with patch("taskloop_dash.jsonl.parse", side_effect=AssertionError("old log reparsed")):
            self.ingest()
        path = self.paths[0]
        with path.open("ab") as file:
            file.write(b',"t":123}\n')
        self.ingest()
        con = must(factorydb.open_ro(self.cfg.factory_db()))
        self.addCleanup(con.close)
        self.assertEqual(con.execute("SELECT offset FROM source WHERE path=?", (str(path),)).fetchone()[0], path.stat().st_size)

    def test_other_writers_survive_update_deletion_and_reindex(self):
        self.ingest()
        con = must(factorydb.open_rw(self.cfg.factory_db()))
        run = self.rows()[0][0]
        con.execute("UPDATE run SET writer='engine:1' WHERE run=?", (run,))
        before = con.execute("SELECT * FROM run WHERE run=?", (run,)).fetchone()
        self.paths[0].unlink()
        self.ingest()
        reindex(self.cfg, clock=lambda: NOW)
        self.assertEqual(con.execute("SELECT * FROM run WHERE run=?", (run,)).fetchone(), before)
        con.close()

    def test_snapshot_reads_no_run_files(self):
        self.ingest()
        original = builtins.open

        def guarded(path, *args, **kwargs):
            if isinstance(path, (str, Path)) and Path(path).is_relative_to(self.cfg.root):
                self.assertNotIn(Path(path).relative_to(self.cfg.root).parts[0], ("engine", "runs"))
            return original(path, *args, **kwargs)

        dash = Dash(Env(self.cfg.root, clock=lambda: NOW))
        with patch("builtins.open", guarded), patch("io.open", guarded):
            world = dash.reads.worlds.world()
            self.assertTrue(world.runs)
            dash.reads.snapshot()

    def test_drawer_and_live_use_only_the_log_reader(self):
        self.ingest()
        dash = Dash(Env(self.cfg.root, clock=lambda: NOW))
        with patch("taskloop_dash.readers.logs.Logs.records", return_value=()) as history, \
                patch("taskloop_dash.readers.logs.Logs.read", return_value=((), "")) as tail, \
                patch("builtins.open", side_effect=AssertionError("caller opened a run log")):
            self.assertTrue(dash.reads.worlds.bead_runs("/repo", "b-0"))
            history.assert_called_once_with(self.paths[0].stem)
            feed = dash.live.live_run(self.paths[0].stem)
            feed.refresh()
            tail.assert_called_once()

    def test_facts_do_not_grow_with_log_lines(self):
        for run, count in (("short", 10), ("long_", 1000)):
            bundle = manifest(self.cfg, run, "b", NOW)
            bundle.log.write_text((json.dumps({"v": 3, "kind": "beat", "t": NOW}) + "\n") * count)
            os.utime(bundle.log, (NOW, NOW))
        self.ingest()
        con = must(factorydb.open_ro(self.cfg.factory_db()))
        try:
            sizes = con.execute("SELECT length(facts) FROM run WHERE run IN ('short','long_')").fetchall()
            self.assertEqual(sizes[0], sizes[1])
        finally:
            con.close()

    def test_budget_carries_work_and_commits_matching_cursors(self):
        with Indexer(self.cfg, clock=lambda: NOW) as index:
            self.assertFalse(index.pass_once(budget=0))
            self.assertEqual(len(self.rows()), 1)
            self.assertEqual(self.rows()[0][2], self.sources()[0][7])
        self.ingest()
        incremental = self.rows()
        reindex(self.cfg, clock=lambda: NOW)
        self.assertEqual(self.rows(), incremental)

    def test_cached_snapshot_drops_run_data_as_soon_as_db_is_stale(self):
        self.ingest()
        now = [NOW]
        dash = Dash(Env(self.cfg.root, clock=lambda: now[0]))
        world, first = dash.reads.built()
        self.assertTrue(world.runs)
        self.assertFalse(first.server.database_error)
        now[0] += 6
        with patch("taskloop_dash.readers.logs.Logs.records", side_effect=AssertionError("unexpected log read for state")):
            world, stale = dash.reads.built()
            self.assertEqual(world.runs, {})
            self.assertTrue(stale.server.database_error)

    def test_unreadable_source_reports_error_and_recovers(self):
        self.ingest()
        original = Path.open

        def blocked(path, *args, **kw):
            if path == self.paths[0]:
                raise PermissionError("test source unreadable")
            return original(path, *args, **kw)

        with patch.object(Path, "open", blocked):
            self.ingest()
        self.assertIn("source unreadable", factorydb.database_error(self.cfg.factory_db(), NOW))
        self.ingest()
        self.assertEqual(factorydb.database_error(self.cfg.factory_db(), NOW), "")

    def test_vanished_manifest_removes_only_its_derived_rows(self):
        self.ingest()
        run = self.paths[0].stem
        self.cfg.run_manifest(run).unlink()
        self.ingest()
        self.assertNotIn(run, [r[0] for r in self.rows()])
        self.assertNotIn(str(self.paths[0]), [s[0] for s in self.sources()])

    def test_missing_wrong_corrupt_and_stale_db_show_no_runs(self):
        for kind in ("missing", "wrong", "corrupt", "stale"):
            with self.subTest(kind=kind):
                reindex(self.cfg, clock=lambda: NOW)
                path = self.cfg.factory_db()
                if kind == "missing":
                    path.unlink()
                elif kind == "corrupt":
                    path.write_bytes(b"broken database")
                else:
                    con = must(factorydb.open_rw(path))
                    con.execute("PRAGMA user_version=99" if kind == "wrong" else "UPDATE kv SET t=0 WHERE k='index.run.pass'")
                    con.close()
                dash = Dash(Env(self.cfg.root, clock=lambda: NOW))
                with patch("taskloop.contracts.locator.RunLocator.runs", side_effect=AssertionError("unexpected run-file read")):
                    world = dash.reads.worlds.world()
                    self.assertFalse(world.runs)
                    self.assertTrue(world.database_error)
                    self.assertTrue(dash.reads.snapshot().server.database_error)
                self.ingest()
                self.assertTrue(self.rows())
        self.assertTrue(list(self.cfg.root.glob("factory.db.bad-*")))


class LogBoundary(fixtures.ApiFixture):
    def test_drawer_and_live_api_use_the_log_reader(self):
        self.dash.reads.snapshot()
        original = builtins.open

        def guarded(path, *args, **kw):
            if isinstance(path, (str, Path)) and Path(path).is_relative_to(self.cfg):
                self.assertNotIn(Path(path).relative_to(self.cfg).parts[0], ("engine", "runs"))
            return original(path, *args, **kw)

        with patch("builtins.open", guarded), patch("io.open", guarded), \
                patch("taskloop_dash.readers.logs.Logs.records", return_value=()) as history, \
                patch("taskloop_dash.readers.logs.Logs.read", return_value=((), "")) as tail, \
                patch("taskloop_dash.readers.logs.Logs.console", return_value=[]), \
                patch("taskloop_dash.readers.logs.Logs.calls", return_value={}):
            detail = self.dash.reads.bead(loop_key(self.repo), "b-1")
            self.assertIsNotNone(detail)
            code, _ = self.dash.live.page(loop_key(self.repo), "b-1")
            self.assertEqual(code, 200)
        history.assert_called_once_with("b-1-20261015-100000")
        tail.assert_called()
