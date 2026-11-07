"""A live engine or surviving worker keeps its checkout during landing and resume."""
from types import SimpleNamespace
from unittest import mock

import pytest
from support import homes
from support.memstores import fake_stores

from land.test_cleanup import CleanupGit
from taskloop.app.land import cleanup
from taskloop.app.land.tree import Tree
from taskloop.app.slots.reset import leave_slot
from taskloop.stores.runlog import RunLog
from tlkernel.locks import EngineLock
from tltestkit.case import Case


class Ownership(Case):
    def setup_method(self):
        self.git = CleanupGit()
        self.log = RunLog(fake_stores().run_log("run"))
        self.lock = self.enterContext(mock.patch("taskloop.app.slots.engine_lock.read_engine_lock"))
        self.alive = self.enterContext(mock.patch("taskloop.app.slots.engine_lock.proc_alive", return_value=True))
        self.agents = self.enterContext(mock.patch("taskloop.app.slots.engine_lock.running_for", return_value=["r1"]))

    def test_cleanup_keeps_live_engine_and_orphan_worker_checkouts(self):
        for slot in (False, True):
            for lock in (EngineLock(pid=987654, started=1, bead="a"),
                         EngineLock(pid=0, started=1, bead="a")):
                with self.subTest(slot=slot, lock=lock):
                    self.lock.return_value = lock
                    why = cleanup.tidy_local(self.git, "/repo", self.log, "task/a", "head", lambda _, slot=slot: slot, cfg=homes.cfg())
                    assert ("pid 987654" in why) or ("run r1" in why)
                    assert self.git.calls == []
                    assert self.git.local == "head"

    def test_cleanup_still_cleans_dead_and_absent_locks(self):
        self.alive.return_value = False
        self.agents.return_value = []
        for slot in (False, True):
            for lock in (None, EngineLock(pid=987654, started=1, bead="a")):
                with self.subTest(slot=slot, lock=lock):
                    self.git = CleanupGit()
                    self.lock.return_value = lock
                    why = cleanup.tidy_local(self.git, "/repo", self.log, "task/a", "head", lambda _, slot=slot: slot, cfg=homes.cfg())
                    assert why == ""
                    assert self.git.ran("detach" if slot else "remove")

    def test_tree_resume_refuses_a_busy_checkout(self):
        self.lock.return_value = EngineLock(pid=987654, started=1, bead="a")
        host = SimpleNamespace(wt="/here", home=mock.Mock(), git=self.git, log=self.log, warn=mock.Mock(),
                               blocked_for=lambda why, kind: RuntimeError(why))
        with pytest.raises(RuntimeError, match="pid 987654"):
            Tree(host).free_branch("task/a")
        host.warn.assert_called_once()
        assert not self.git.ran("detach")

    def test_leave_slot_refuses_a_busy_checkout_before_reading_dirty_status(self):
        self.lock.return_value = EngineLock(pid=987654, started=1, bead="a")
        dirty = mock.Mock(return_value=False)
        assert not leave_slot(homes.cfg(), self.git, "/wt", "origin/main", "task/a", dirty=dirty)
        dirty.assert_not_called()
        assert not self.git.ran("detach")

    def test_leave_slot_reads_fresh_dirty_status_after_the_busy_check(self):
        self.lock.side_effect = lambda _cfg, _wt: setattr(self.git, "dirty_tree", True)
        assert not leave_slot(homes.cfg(), self.git, "/wt", "origin/main", "task/a", dirty=lambda: self.git.dirty_tree)
        assert not self.git.ran("detach")
