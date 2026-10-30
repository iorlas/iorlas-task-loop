"""The applier runs the planned actions: each delete carries the oid it was observed at, and a branch waits for its tree."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.git import RealGit
from taskloop.app.reconcile.apply import apply
from taskloop.app.reconcile.observe import lease_of
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.slots import SlotGitError
from taskloop.domain.reconcile.facts import Action, DeleteBranch, DeleteRemote, Keep, RemoveTree


class FakeGit(RealGit):
    """The compare-and-delete and remove calls, recorded (nothing runs); `fail` names the call that is refused."""

    def __init__(self, fail: str = "") -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail = fail

    def refuse(self, *call: str) -> None:
        self.calls.append(call)
        if self.fail == call[0]:
            raise SlotGitError("fatal: refused")

    def delete_branch_at(self, d: str, branch: str, oid: str) -> None:
        self.refuse("delete_branch_at", branch, oid)

    def delete_remote_at(self, d: str, remote: str, ref: str, oid: str) -> None:
        self.refuse("delete_remote_at", remote, ref, oid)

    def remove_worktree_why(self, repo: str, path: str) -> str:
        try:
            self.refuse("remove_worktree_why", path)
        except SlotGitError as e:
            return e.tail
        return ""


class Apply(unittest.TestCase):
    def test_each_delete_passes_the_oid_it_was_planned_at(self):
        sh = FakeGit()
        removed, kept = apply([DeleteBranch("/r", "r", "task/a", "abc"), DeleteRemote("/r", "r", "refs/heads/task/a", "def")], False, sh)
        self.assertEqual(sh.calls, [("delete_branch_at", "task/a", "abc"), ("delete_remote_at", "origin", "refs/heads/task/a", "def")])
        self.assertEqual((len(removed), kept), (2, []))

    def test_a_moved_branch_stays_with_gits_reason(self):
        removed, kept = apply([DeleteBranch("/r", "r", "task/a", "abc")], False, FakeGit(fail="delete_branch_at"))
        self.assertEqual((removed, kept), ([], ["branch task/a (r): fatal: refused"]))

    def test_a_branch_stays_when_the_tree_that_held_it_could_not_go(self):
        plan: list[Action] = [RemoveTree("/r", "/b/t", "/b/t"), DeleteBranch("/r", "r", "release/x", "abc", ("/b/t",))]
        sh = FakeGit(fail="remove_worktree_why")
        removed, kept = apply(plan, False, sh)
        self.assertEqual(removed, [])
        self.assertEqual(kept[1], "branch release/x (r): a worktree still has it")
        self.assertNotIn(("delete_branch_at", "release/x", "abc"), sh.calls)

    def test_the_dry_run_runs_nothing(self):
        sh = FakeGit()
        removed, kept = apply([DeleteBranch("/r", "r", "task/a", "abc"), Keep("worktree /w", "this shell is in it")], True, sh)
        self.assertEqual(sh.calls, [])
        self.assertEqual((removed, kept), (["would remove branch task/a (r)"], ["worktree /w: this shell is in it"]))


class Leases(unittest.TestCase):
    def test_a_held_bead_has_a_lease_at_its_fence_generation(self):
        b = Bead(id=BeadId("a-1"), title="", status="in_progress", assignee="tl-x", metadata={"fence_gen": "3"}, lease_expires_at="t")
        ls = lease_of(b)
        self.assertEqual((ls.holder, ls.gen, ls.expires), ("tl-x", 3, "t")) if ls else self.fail("no lease")

    def test_closed_or_unassigned_beads_hold_no_lease(self):
        self.assertIsNone(lease_of(Bead(id=BeadId("a-1"), title="", status="closed", assignee="x")))
        self.assertIsNone(lease_of(Bead(id=BeadId("a-1"), title="", status="open")))


if __name__ == "__main__":
    unittest.main()
