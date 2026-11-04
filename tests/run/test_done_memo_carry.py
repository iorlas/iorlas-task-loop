"""A network continuation copies only consumed SQL steps after creating its run."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import support.paths  # noqa: F401

from taskloop.app.run import done_memo
from taskloop.app.run.reload import Reload
from taskloop.contracts import factorydb
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir, RunFiles


class CarryDoneMemo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.where = RunLocator(self.cfg)
        self.paused = self.where.create("/repo", "b", 10)
        self.new = self.where.create("/repo", "b", 20)
        self.host = SimpleNamespace(home=self.cfg, run_id=self.new.run, run_dir=self.new.dir)

    def steps(self, run):
        with self.where.rows.transaction() as con:
            return con.execute("SELECT key,try,attempt,status,started,ended,input_digest,result,fingerprint,calls "
                               "FROM step WHERE run=? ORDER BY key", (run,)).fetchall()

    def test_copy_keeps_receipts_and_identity_filters_pending_steps_and_does_not_reread_files(self):
        answer = self.paused.dir / "answer.json"
        answer.write_text('{"answer": "done"}')
        done_memo.keep(self.paused.dir, ("write", 1), "sha", str(answer))
        with self.where.rows.transaction() as con:
            con.execute("INSERT INTO step (run,key,try,attempt,status,started) VALUES (?, '[2]',1,1,'running',10)",
                        (self.paused.run,))
        before = self.steps(self.paused.run)
        with patch.object(RunFiles, "done_memo", side_effect=AssertionError("legacy file read")):
            Reload(self.host).carry_done_memo(self.paused.dir)
        self.assertEqual(self.steps(self.new.run), [row for row in before if row[3] == "done"])
        self.assertEqual(self.steps(self.paused.run), before)
        self.assertEqual(done_memo.recall(self.new.dir, ("write", 1), "sha"), {"answer": "done"})
        self.assertIsNone(done_memo.recall(self.new.dir, ("write", 1), "changed"))
        done_memo.keep(self.new.dir, ("write", 1), "new-sha", str(answer))
        Reload(self.host).carry_done_memo(self.paused.dir)
        self.assertEqual(self.steps(self.new.run)[0][6], "new-sha")

    def test_copy_requires_destination_run_and_rolls_back_on_foreign_key_failure(self):
        answer = self.paused.dir / "answer.json"
        answer.write_text('{}')
        done_memo.keep(self.paused.dir, (1,), "sha", str(answer))
        self.host.run_id = "missing"
        with self.assertRaises(factorydb.DatabaseError):
            Reload(self.host).carry_done_memo(self.paused.dir)
        self.assertEqual(self.steps("missing"), [])
