"""The applier runs the planned actions: each delete carries the oid it was observed at, and a branch waits for its tree."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.reconcile.apply import apply
from taskloop.app.reconcile.observe import lease_of
from taskloop.app.release.shell import Done, Shell
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.domain.reconcile.facts import Action, DeleteBranch, DeleteRemote, Keep, RemoveTree


class FakeShell(Shell):
    def __init__(self, fail: str = "") -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def run(self, cmd: list[str], cwd: str | Path, check: bool = True) -> Done:
        self.calls.append(cmd)
        bad = self.fail and self.fail in cmd
        return Done(1 if bad else 0, "", "fatal: refused" if bad else "")


class Apply(unittest.TestCase):
    def test_each_delete_passes_the_oid_it_was_planned_at(self):
        sh = FakeShell()
        removed, kept = apply([DeleteBranch("/r", "r", "task/a", "abc"), DeleteRemote("/r", "r", "refs/heads/task/a", "def")], False, sh)
        self.assertEqual(sh.calls, [["git", "update-ref", "-d", "refs/heads/task/a", "abc"],
                                    ["git", "push", "--force-with-lease=refs/heads/task/a:def", "origin", ":refs/heads/task/a"]])
        self.assertEqual((len(removed), kept), (2, []))

    def test_a_moved_branch_stays_with_gits_reason(self):
        removed, kept = apply([DeleteBranch("/r", "r", "task/a", "abc")], False, FakeShell(fail="update-ref"))
        self.assertEqual((removed, kept), ([], ["branch task/a (r): fatal: refused"]))

    def test_a_branch_stays_when_the_tree_that_held_it_could_not_go(self):
        plan: list[Action] = [RemoveTree("/r", "/b/t", "/b/t"), DeleteBranch("/r", "r", "release/x", "abc", ("/b/t",))]
        sh = FakeShell(fail="remove")
        removed, kept = apply(plan, False, sh)
        self.assertEqual(removed, [])
        self.assertEqual(kept[1], "branch release/x (r): a worktree still has it")
        self.assertNotIn(["git", "update-ref", "-d", "refs/heads/release/x", "abc"], sh.calls)

    def test_the_dry_run_runs_nothing(self):
        sh = FakeShell()
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
