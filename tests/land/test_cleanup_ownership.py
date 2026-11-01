"""A live engine or surviving worker keeps its checkout during landing and resume."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from land.test_cleanup import CleanupGit
from taskloop.app.land import cleanup
from taskloop.app.land.tree import Tree
from taskloop.app.slots.reset import leave_slot
from taskloop.contracts.locks import EngineLock
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class Ownership(unittest.TestCase):
    def setUp(self):
        self.git = CleanupGit()
        self.log = RunLog(fake_stores().run_log("run"))
        self.lock = self.enterContext(mock.patch("taskloop.app.slots.engine_lock.read_engine_lock"))
        self.alive = self.enterContext(mock.patch("taskloop.app.slots.engine_lock.proc_alive", return_value=True))

    def test_cleanup_keeps_live_engine_and_orphan_worker_checkouts(self):
        for slot in (False, True):
            for lock in (EngineLock(pid=987654, started=1, bead="a"),
                         EngineLock(pid=0, started=1, bead="a", workers=[(987654, "start")])):
                with self.subTest(slot=slot, lock=lock):
                    self.lock.return_value = lock
                    why = cleanup.tidy_local(self.git, "/repo", self.log, "task/a", "head", lambda _, slot=slot: slot)
                    self.assertIn("pid 987654", why)
                    self.assertEqual(self.git.calls, [])
                    self.assertEqual(self.git.local, "head")

    def test_cleanup_still_cleans_dead_and_absent_locks(self):
        self.alive.return_value = False
        for slot in (False, True):
            for lock in (None, EngineLock(pid=987654, started=1, bead="a")):
                with self.subTest(slot=slot, lock=lock):
                    self.git = CleanupGit()
                    self.lock.return_value = lock
                    self.assertEqual(cleanup.tidy_local(self.git, "/repo", self.log, "task/a", "head", lambda _, slot=slot: slot), "")
                    self.assertTrue(self.git.ran("detach" if slot else "remove"))

    def test_tree_resume_refuses_a_busy_checkout(self):
        self.lock.return_value = EngineLock(pid=987654, started=1, bead="a")
        host = SimpleNamespace(wt="/here", git=self.git, log=self.log, warn=mock.Mock(), blocked_for=lambda why, kind: RuntimeError(why))
        with self.assertRaisesRegex(RuntimeError, "pid 987654"):
            Tree(host).free_branch("task/a")
        host.warn.assert_called_once()
        self.assertFalse(self.git.ran("detach"))

    def test_leave_slot_refuses_a_busy_checkout_before_reading_dirty_status(self):
        self.lock.return_value = EngineLock(pid=987654, started=1, bead="a")
        dirty = mock.Mock(return_value=False)
        self.assertFalse(leave_slot(self.git, "/wt", "origin/main", "task/a", dirty=dirty))
        dirty.assert_not_called()
        self.assertFalse(self.git.ran("detach"))

    def test_leave_slot_reads_fresh_dirty_status_after_the_busy_check(self):
        self.lock.side_effect = lambda _wt: setattr(self.git, "dirty_tree", True)
        self.assertFalse(leave_slot(self.git, "/wt", "origin/main", "task/a", dirty=lambda: self.git.dirty_tree))
        self.assertFalse(self.git.ran("detach"))
