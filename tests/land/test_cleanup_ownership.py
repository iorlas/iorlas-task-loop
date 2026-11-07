"""A live engine or surviving worker keeps its checkout during landing and resume."""
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import homes
from support.memstores import fake_stores

from land.test_cleanup import CleanupGit
from taskloop.app.wire.slotfx import FX
from taskloop.app.land import cleanup
from taskloop.app.land.tree import Tree
from tlslots.reset import leave_slot
from taskloop.stores.runlog import RunLog
from tlkernel.locks import EngineLock


class Ownership(Case):
    def setup_method(self):
        self.git = CleanupGit()
        self.log = RunLog(fake_stores().run_log("run"))
        self.lock = self.enterContext(mock.patch("tlslots.engine_lock.read_engine_lock"))
        self.alive = mock.Mock(return_value=True)
        self.agents = mock.Mock(return_value=["r1"])
        self.fx = replace(FX, proc_alive=self.alive, running_for=self.agents)

    def test_cleanup_keeps_live_engine_and_orphan_worker_checkouts(self):
        for slot in (False, True):
            for lock in (EngineLock(pid=987654, started=1, bead="a"),
                         EngineLock(pid=0, started=1, bead="a")):
                with self.subTest(slot=slot, lock=lock):
                    self.lock.return_value = lock
                    why = cleanup.tidy_local(self.git, "/repo", self.log, "task/a", "head", lambda _, slot=slot: slot, cfg=homes.cfg(), fx=self.fx)
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
                    why = cleanup.tidy_local(self.git, "/repo", self.log, "task/a", "head", lambda _, slot=slot: slot, cfg=homes.cfg(), fx=self.fx)
                    assert why == ""
                    assert self.git.ran("detach" if slot else "remove")

    def test_tree_resume_refuses_a_busy_checkout(self):
        self.lock.return_value = EngineLock(pid=987654, started=1, bead="a")
        host = SimpleNamespace(wt="/here", home=mock.Mock(), git=self.git, log=self.log, warn=mock.Mock(),
                               blocked_for=lambda why, kind: RuntimeError(why))
        with pytest.raises(RuntimeError, match="pid 987654"):
            Tree(host, fx=self.fx).free_branch("task/a")
        host.warn.assert_called_once()
        assert not self.git.ran("detach")

    def test_leave_slot_refuses_a_busy_checkout_before_reading_dirty_status(self):
        self.lock.return_value = EngineLock(pid=987654, started=1, bead="a")
        dirty = mock.Mock(return_value=False)
        assert not leave_slot(homes.cfg(), self.git, "/wt", "origin/main", "task/a", dirty=dirty, fx=self.fx)
        dirty.assert_not_called()
        assert not self.git.ran("detach")

    def test_leave_slot_reads_fresh_dirty_status_after_the_busy_check(self):
        self.lock.side_effect = lambda _cfg, _wt: setattr(self.git, "dirty_tree", True)
        assert not leave_slot(homes.cfg(), self.git, "/wt", "origin/main", "task/a", dirty=lambda: self.git.dirty_tree, fx=self.fx)
        assert not self.git.ran("detach")
