"""Post-land cleanup keeps its original leases and can fail independently of the landing receipt."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import homes
from support.fakegit import ScriptedGit

# isort: split
from support.memstores import fake_stores

from taskloop.app.land import cleanup
from taskloop.app.land.closing import LandCleanups
from taskloop.app.pipeline.closing_branch import ReleaseSlot
from taskloop.stores.runlog import RunLog
from tlkernel import fence
from tlkernel import log as rec
from tlkernel.enums import Outcome
from tlkernel.ids import BeadId
from tlkernel.slots import Checkout, GitReadFailure, SlotGitError


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

    def dirty(self, d):
        return self.dirty_tree

    def branch(self, d):
        return next(co.branch for co in self.worktrees if co.path == d)

    def checkout_detached(self, d, ref):
        self.seen("detach", d, ref)
        self.worktrees = [co.replace(branch="") if co.path == d else co for co in self.worktrees]

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


class Cleanup(Case):
    def test_failed_reads_keep_local_cleanup_pending_without_mutating(self):
        for method in ("rev_parse", "checkouts", "dirty", "branch"):
            with self.subTest(method=method):
                self.git.calls.clear()
                with mock.patch.object(self.git, method, side_effect=GitReadFailure("unreadable")):
                    done = cleanup.retry(self.git, self.log, self.queue(pr=True), lambda path: True, cfg=homes.cfg())
                assert done.local_outcome == "pending"
                assert "unreadable" in done.detail
                assert self.git.calls == []
                assert self.git.local == "head"

    def setup_method(self):
        self.git = CleanupGit()
        self.log = RunLog(fake_stores().run_log("run"))

    def queue(self, pr=False):
        return cleanup.record(self.log, "/repo", "task/a", "head", "land", "" if pr else "origin", "" if pr else "wip")

    def test_push_land_removes_worktree_and_both_refs_and_records_outcomes(self):
        done = cleanup.retry(self.git, self.log, self.queue(), cfg=homes.cfg())
        assert (done.local_outcome, done.remote_outcome) == ("gone", "gone")
        assert (self.git.local, self.git.remote) == ("", "")
        assert [co.path for co in self.git.worktrees] == ["/repo"]
        rows = [item.rec for item in self.log.log.read_from(0).items]
        assert isinstance(rows[0], rec.LandReceipt)
        queued = rows[1]
        assert isinstance(queued, rec.LandCleanup)
        assert queued.local_outcome == "pending"

    def test_pr_land_never_calls_remote_delete_even_when_head_still_exists(self):
        done = cleanup.retry(self.git, self.log, self.queue(pr=True), cfg=homes.cfg())
        assert done.remote_outcome == "skipped"
        assert self.git.remote == "wip"
        assert not self.git.ran("delete_remote")

    def test_slot_is_detached_at_its_base_and_only_the_branch_is_deleted(self):
        done = cleanup.retry(self.git, self.log, self.queue(), lambda path: path == "/wt", "origin/trunk", cfg=homes.cfg())
        assert done.local_outcome == "gone"
        assert [co.path for co in self.git.worktrees] == ["/repo", "/wt"]
        assert self.git.ran("detach", "/wt", "origin/trunk")
        assert not self.git.ran("remove")
        assert self.git.local == ""

    def test_unsaved_slot_work_keeps_its_branch_and_directory_for_retry(self):
        self.git.dirty_tree = True
        done = cleanup.retry(self.git, self.log, self.queue(), lambda path: path == "/wt", cfg=homes.cfg())
        assert done.local_outcome == "pending"
        assert not self.git.ran("remove")
        assert not self.git.ran("detach")

    def test_unavailable_slot_registry_keeps_the_worktree_and_branch_retryable(self):
        lookup = mock.Mock(side_effect=RuntimeError("slot registry unavailable"))
        done = cleanup.retry(self.git, self.log, self.queue(), lookup, cfg=homes.cfg())
        assert done.local_outcome == "pending"
        assert not self.git.ran("remove")
        assert self.git.local == "head"

    def test_moved_local_and_remote_refs_keep_their_new_work(self):
        row = self.queue()
        self.git.local = self.git.remote = "new"
        done = cleanup.retry(self.git, self.log, row, cfg=homes.cfg())
        assert (done.local_outcome, done.remote_outcome) == ("pending", "pending")
        assert (self.git.local, self.git.remote) == ("new", "new")
        assert not self.git.ran("remove")

    def test_a_move_during_delete_is_protected_by_the_local_compare_oid(self):
        row = self.queue()
        self.git.before_delete = lambda: setattr(self.git, "local", "new")
        done = cleanup.retry(self.git, self.log, row, cfg=homes.cfg())
        assert done.local_outcome == "pending"
        assert self.git.local == "new"

    def test_dirty_worktree_failure_is_retryable_with_the_original_oids(self):
        self.git.dirty_tree = True
        done = cleanup.retry(self.git, self.log, self.queue(), cfg=homes.cfg())
        assert (done.local_outcome, done.remote_outcome) == ("pending", "gone")
        assert "untracked files" in done.detail
        self.git.dirty_tree = False
        cleanup.retry_logged(self.git, self.log, cfg=homes.cfg())
        assert self.git.local == ""
        assert self.git.calls.count(("delete_remote", "wip")) == 1

    def test_cleanup_runs_after_the_slot_close_and_is_not_lost_when_already_gone(self):
        self.queue()
        self.git.remote = ""
        tree = SimpleNamespace(leave_slot=mock.Mock())
        host = SimpleNamespace(tree=tree, git=self.git, log=self.log, claim=fence.offline(BeadId("a")),
                               wt="/repo", who=mock.Mock(), store=mock.Mock(), home=homes.cfg())
        def leave_slot(*args):
            assert self.git.local == "head"
        tree.leave_slot.side_effect = leave_slot
        cleanups = LandCleanups(self.git, self.log, homes.cfg(), lambda repo: (lambda path: False), lambda repo: "main")
        ReleaseSlot(host, tree, cleanups).run("task/a", Outcome.LANDED)
        tree.leave_slot.assert_called_once()
        assert self.git.local == ""
        cleanup.retry_logged(self.git, self.log, cfg=homes.cfg())
        assert self.git.calls.count(("delete_remote", "wip")) == 1

    def test_the_main_checkout_is_kept(self):
        self.git.worktrees = [Checkout(path="/repo", branch="task/a", main=True)]
        done = cleanup.retry(self.git, self.log, self.queue(), cfg=homes.cfg())
        assert done.local_outcome == "pending"
        assert "main checkout" in done.detail

    def test_a_repeated_receipt_does_not_adopt_new_remote_work(self):
        row = self.queue()
        self.git.remote = "new"
        again = cleanup.record(self.log, "/repo", "task/a", "head", "land", "origin", "new", prior=row)
        assert again.remote_oid == "wip"
        done = cleanup.retry(self.git, self.log, again, cfg=homes.cfg())
        assert done.remote_outcome == "pending"
        assert self.git.remote == "new"
