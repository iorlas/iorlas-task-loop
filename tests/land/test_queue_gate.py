"""The gate of a queue entry: `require(base_override=Q(N-1))` judges at that parent and never at the base branch, and `judge_queue` runs
`tl check --base-commit` on Q(N) and says whether the gate steps have their receipts at that tree and base."""
import threading
from pathlib import Path
from unittest import mock

import pytest
from support.memstores import fake_stores

from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.stackgate import StackGate
from taskloop.stores.runlog import RunLog
from tlkernel.procport import Ran
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

from .test_stackgate_keys import OID, Checkouts, write_receipts

PARENT = "queue-parent"


class QueueGate(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Checkouts(Path(tmp.name))
        self.stores = fake_stores()
        self.spawner = mock.Mock()
        self.spawner.run.return_value = Ran(exit=0)
        log = RunLog(self.stores.run_log("land"), run_id="land", host="h")
        self.gate = StackGate(Cmds(self.spawner, log, str(self.repo.main)), self.repo.git, self.stores, str(self.repo.main),
                              "origin/main", ["tl"])
        rev = self.repo.git.rev_parse.side_effect
        self.asked: list[str] = []
        self.repo.git.rev_parse.side_effect = lambda d, r: self.asked.append(r) or (PARENT if r == PARENT else rev(d, r))

    def test_the_override_is_the_base_and_the_base_branch_is_never_asked(self):
        self.repo.git.checkouts.return_value = self.repo.git.checkouts.return_value[:1]  # the gate makes its own worktree
        with pytest.raises(Stop):
            self.gate.require("task/a", OID, base_override=PARENT)
        argv = self.spawner.run.call_args.args[0]
        assert argv[argv.index("--base-commit") + 1] == PARENT
        assert "origin/main" not in self.asked

    def test_main_moving_during_a_queued_gate_does_not_regate(self):
        self.repo.git.checkouts.return_value = self.repo.git.checkouts.return_value[:1]
        with pytest.raises(Stop):
            self.gate.require("task/a", OID, base_override=PARENT)
        assert self.spawner.run.call_count == 1

    def test_without_the_override_the_check_gets_no_base_commit(self):
        self.repo.git.checkouts.return_value = self.repo.git.checkouts.return_value[:1]
        with pytest.raises(Stop):
            self.gate.require("task/a", OID)
        assert "--base-commit" not in self.spawner.run.call_args.args[0]

    def test_judge_queue_is_false_when_the_check_left_no_receipts_and_removes_its_worktree(self):
        assert self.gate.judge_queue(OID, PARENT, threading.Lock()) is False
        argv = self.spawner.run.call_args.args[0]
        assert argv[:2] == ["tl", "check"] and argv[argv.index("--base-commit") + 1] == PARENT
        assert self.repo.git.remove_worktree_force.called

    def test_judge_queue_is_true_when_the_receipts_are_at_the_tree_and_the_parent(self):
        wt = []
        self.repo.git.add_worktree.side_effect = lambda repo, path, oid: wt.append(path)
        self.spawner.run.side_effect = lambda *a, **k: write_receipts(self.stores, self.repo.git, wt[0], base=PARENT) and Ran(exit=0)
        assert self.gate.judge_queue(OID, PARENT, threading.Lock()) is True

    def test_a_profile_change_does_not_ride_the_queue(self):
        self.repo.git.ls_tree.side_effect = lambda d, rev, *p, recursive=False: (
            [mock.Mock(oid=rev)] if p else Checkouts.ls_tree(d, rev, *p, recursive=recursive))
        assert self.gate.judge_queue(OID, PARENT, threading.Lock()) is False
        self.spawner.run.assert_not_called()
