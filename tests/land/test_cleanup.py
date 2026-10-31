"""Post-land cleanup keeps its original leases and can fail independently of the landing receipt."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import ScriptedGit

# isort: split
from taskloop.app.land import cleanup
from taskloop.app.run.closer_branch import ReleaseSlot
from taskloop.contracts import fence
from taskloop.contracts import log as rec
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import BeadId
from taskloop.contracts.slots import Checkout, SlotGitError
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class CleanupGit(ScriptedGit):
    def __init__(self):
        super().__init__()
        self.local, self.remote = "head", "wip"
        self.worktrees = [Checkout(path="/repo", branch="main", main=True),
                          Checkout(path="/wt", branch="task/a", main=False)]
        self.dirty_tree = False
        self.before_delete = lambda: None

    def rev_parse(self, d, rev):
        return self.local

    def checkouts(self, d):
        return self.worktrees

    def remove_worktree_why(self, repo, path):
        if self.dirty_tree:
            return "untracked files"
        self.seen("remove", path)
        self.worktrees = [co for co in self.worktrees if co.path != path]
        return ""

    def delete_branch_at(self, d: str, branch: str, oid: str) -> None:
        self.before_delete()
        if self.local != oid:
            raise SlotGitError("moved")
        self.seen("delete_local", oid)
        self.local = ""

    def delete_remote_at(self, d: str, remote: str, ref: str, oid: str) -> None:
        self.seen("delete_remote", oid)
        if self.remote and self.remote != oid:
            raise SlotGitError("stale info")
        self.remote = ""


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.git = CleanupGit()
        self.log = RunLog(fake_stores().run_log("run"))

    def queue(self, pr=False):
        return cleanup.record(self.log, "/repo", "task/a", "head", "land", "" if pr else "origin", "" if pr else "wip")

    def test_push_land_removes_worktree_and_both_refs_and_records_outcomes(self):
        done = cleanup.retry(self.git, self.log, self.queue())
        self.assertEqual((done.local_outcome, done.remote_outcome), ("gone", "gone"))
        self.assertEqual((self.git.local, self.git.remote), ("", ""))
        self.assertEqual([co.path for co in self.git.worktrees], ["/repo"])
        rows = [item.rec for item in self.log.log.read_from(0).items]
        self.assertIsInstance(rows[0], rec.LandReceipt)
        queued = rows[1]
        assert isinstance(queued, rec.LandCleanup)
        self.assertEqual(queued.local_outcome, "pending")

    def test_pr_land_never_calls_remote_delete_even_when_head_still_exists(self):
        done = cleanup.retry(self.git, self.log, self.queue(pr=True))
        self.assertEqual(done.remote_outcome, "skipped")
        self.assertEqual(self.git.remote, "wip")
        self.assertFalse(self.git.ran("delete_remote"))

    def test_moved_local_and_remote_refs_keep_their_new_work(self):
        row = self.queue()
        self.git.local = self.git.remote = "new"
        done = cleanup.retry(self.git, self.log, row)
        self.assertEqual((done.local_outcome, done.remote_outcome), ("pending", "pending"))
        self.assertEqual((self.git.local, self.git.remote), ("new", "new"))
        self.assertFalse(self.git.ran("remove"))

    def test_a_move_during_delete_is_protected_by_the_local_compare_oid(self):
        row = self.queue()
        self.git.before_delete = lambda: setattr(self.git, "local", "new")
        done = cleanup.retry(self.git, self.log, row)
        self.assertEqual(done.local_outcome, "pending")
        self.assertEqual(self.git.local, "new")

    def test_dirty_worktree_failure_is_retryable_with_the_original_oids(self):
        self.git.dirty_tree = True
        done = cleanup.retry(self.git, self.log, self.queue())
        self.assertEqual((done.local_outcome, done.remote_outcome), ("pending", "gone"))
        self.assertIn("untracked files", done.detail)
        self.git.dirty_tree = False
        cleanup.retry_logged(self.git, self.log)
        self.assertEqual(self.git.local, "")
        self.assertEqual(self.git.calls.count(("delete_remote", "wip")), 1)

    def test_cleanup_runs_after_the_slot_close_and_is_not_lost_when_already_gone(self):
        self.queue()
        self.git.remote = ""
        tree = SimpleNamespace(leave_slot=mock.Mock())
        host = SimpleNamespace(tree=tree, git=self.git, log=self.log, claim=fence.offline(BeadId("a")))
        tree.leave_slot.side_effect = lambda *args: self.assertEqual(self.git.local, "head")
        ReleaseSlot(host).run("task/a", Outcome.LANDED)
        tree.leave_slot.assert_called_once()
        self.assertEqual(self.git.local, "")
        cleanup.retry_logged(self.git, self.log)
        self.assertEqual(self.git.calls.count(("delete_remote", "wip")), 1)

    def test_the_main_checkout_is_kept(self):
        self.git.worktrees = [Checkout(path="/repo", branch="task/a", main=True)]
        done = cleanup.retry(self.git, self.log, self.queue())
        self.assertEqual(done.local_outcome, "pending")
        self.assertIn("main checkout", done.detail)

    def test_a_repeated_receipt_does_not_adopt_new_remote_work(self):
        row = self.queue()
        self.git.remote = "new"
        again = cleanup.record(self.log, "/repo", "task/a", "head", "land", "origin", "new", prior=row)
        self.assertEqual(again.remote_oid, "wip")
        done = cleanup.retry(self.git, self.log, again)
        self.assertEqual(done.remote_outcome, "pending")
        self.assertEqual(self.git.remote, "new")


if __name__ == "__main__":
    unittest.main()
