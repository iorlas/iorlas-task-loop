"""Reset diagnostics never repair a released slot; branch freeing checks fresh ownership."""
from pathlib import Path
from unittest import mock

from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.slots import Checkout, GitReadFailure

from tlslots import reset
from tlslots.testing import Rig


class ResetOwnership(Rig):

    def test_faults_in_preservation_and_branch_admission_refuse_checkout_and_clean(self):
        for operation in ("branch", "has_branch", "checkouts"):
            with self.subTest(operation=operation):
                self.git.calls.clear()
                self.git.tree(self.d1).dirty = operation == "branch"
                self.git.branches.add("task/x-1")
                self.git.fail(operation, GitReadFailure("cannot read"))
                assert self.code(lambda: self.slot().ready_for("x-1")) == "transient"
                assert not ({"checkout", "checkout_new", "checkout_detached", "clean", "commit_all"}
                                 & {call[0] for call in self.git.calls})

    def test_probe_refuses_a_claimed_slot_without_reading_git(self):
        self.slot().take("another loop")
        assert self.code(self.slot().check_ready) == "busy"
        assert self.git.calls == []

    def test_probe_refuses_live_engine_and_hold_without_reading_git(self):
        self.busy_at[self.d1] = "worker pid 7 outlived its engine"
        assert self.code(self.slot().check_ready) == "busy"
        self.busy_at.clear()
        bid = BeadId("sl-s1")
        self.bd.beads[bid] = Bead(id=bid, title="slot h s1", status="open", labels=["slot"],
                                 metadata={"hold_until": "2000", "held_by": "owner", "held_why": "review"})
        assert self.code(self.slot().check_ready) == "busy"
        assert self.git.calls == []

    def test_probe_reports_missing_and_rebasing_trees_without_repair(self):
        self.git.tree(self.d1).rebasing = True
        assert self.code(self.slot().check_ready) == "slot_broken"
        assert [call[0] for call in self.git.calls] == ["rebasing"]
        self.git.calls.clear()
        Path(self.d1).rmdir()
        assert self.code(self.slot().check_ready) == "slot_broken"
        assert self.git.calls == []

    def test_branch_freeing_rechecks_ownership_before_each_mutation(self):
        branch = "task/x-1"
        self.git.elsewhere[branch] = Checkout(path="/w/old", branch=branch, main=False)
        with mock.patch.object(self.env, "busy", side_effect=["", "engine pid 7 runs x-1"]):
            assert "pid 7" in reset.free_branch(self.slot(), branch)
        assert self.git.removed == []
        assert "checkout_detached" not in [call[0] for call in self.git.calls]

    def test_branch_freeing_rechecks_the_branch_after_ownership_check(self):
        branch = "task/x-1"
        self.git.elsewhere[branch] = Checkout(path="/w/old", branch=branch, main=False)
        self.git.tree("/w/old").branch = "task/new"
        assert "changed branch" in reset.free_branch(self.slot(), branch)
        assert self.git.removed == []
