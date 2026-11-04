"""Reset diagnostics never repair a released slot; branch freeing checks fresh ownership."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from git_porcelain.errors import GitUnavailable

from slots.test_slot_pool import Rig
from taskloop.adapters.git import RealGit
from taskloop.app.slots import reset
from taskloop.contracts.bead import Bead
from taskloop.contracts.env import Env
from taskloop.contracts.ids import BeadId
from taskloop.contracts.slots import Checkout, GitReadFailure


class ResetOwnership(Rig):
    def test_failed_status_in_ready_for_preserves_work_and_refuses_all_mutations(self):
        work = Path(self.d1) / "untracked.txt"
        work.write_text("keep me")
        adapter = RealGit(Env(), pinned=False)
        with (mock.patch.object(adapter, "_pool", side_effect=GitUnavailable("status unavailable")),
              mock.patch.object(self.git, "dirty", side_effect=adapter.dirty),
              mock.patch("taskloop.app.slots.reset.setup") as setup):
            self.assertEqual(self.code(lambda: self.slot().ready_for("x-1")), "transient")
        setup.assert_not_called()
        self.assertEqual(work.read_text(), "keep me")
        self.assertEqual([call[0] for call in self.git.calls], ["rebasing"])

    def test_faults_in_preservation_and_branch_admission_refuse_checkout_and_clean(self):
        for operation in ("branch", "has_branch", "checkouts"):
            with self.subTest(operation=operation):
                self.git.calls.clear()
                self.git.tree(self.d1).dirty = operation == "branch"
                self.git.branches.add("task/x-1")
                self.git.fail(operation, GitReadFailure("cannot read"))
                self.assertEqual(self.code(lambda: self.slot().ready_for("x-1")), "transient")
                self.assertFalse({"checkout", "checkout_new", "checkout_detached", "clean", "commit_all"}
                                 & {call[0] for call in self.git.calls})

    def test_probe_refuses_a_claimed_slot_without_reading_git(self):
        self.slot().take("another loop")
        self.assertEqual(self.code(self.slot().check_ready), "busy")
        self.assertEqual(self.git.calls, [])

    def test_probe_refuses_live_engine_and_hold_without_reading_git(self):
        self.busy_at[self.d1] = "worker pid 7 outlived its engine"
        self.assertEqual(self.code(self.slot().check_ready), "busy")
        self.busy_at.clear()
        bid = BeadId("sl-s1")
        self.bd.beads[bid] = Bead(id=bid, title="slot h s1", status="open", labels=["slot"],
                                 metadata={"hold_until": "2000", "held_by": "owner", "held_why": "review"})
        self.assertEqual(self.code(self.slot().check_ready), "busy")
        self.assertEqual(self.git.calls, [])

    def test_probe_reports_missing_and_rebasing_trees_without_repair(self):
        self.git.tree(self.d1).rebasing = True
        self.assertEqual(self.code(self.slot().check_ready), "slot_broken")
        self.assertEqual([call[0] for call in self.git.calls], ["rebasing"])
        self.git.calls.clear()
        Path(self.d1).rmdir()
        self.assertEqual(self.code(self.slot().check_ready), "slot_broken")
        self.assertEqual(self.git.calls, [])

    def test_branch_freeing_rechecks_ownership_before_each_mutation(self):
        branch = "task/x-1"
        self.git.elsewhere[branch] = Checkout(path="/w/old", branch=branch, main=False)
        with mock.patch.object(self.env, "busy", side_effect=["", "engine pid 7 runs x-1"]):
            self.assertIn("pid 7", reset.free_branch(self.slot(), branch))
        self.assertEqual(self.git.removed, [])
        self.assertNotIn("checkout_detached", [call[0] for call in self.git.calls])

    def test_branch_freeing_rechecks_the_branch_after_ownership_check(self):
        branch = "task/x-1"
        self.git.elsewhere[branch] = Checkout(path="/w/old", branch=branch, main=False)
        self.git.tree("/w/old").branch = "task/new"
        self.assertIn("changed branch", reset.free_branch(self.slot(), branch))
        self.assertEqual(self.git.removed, [])
