"""The applier runs the planned actions: each delete carries the oid it was observed at, and a branch waits for its tree."""
import sys
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads

from taskloop.adapters.git import RealGit
from taskloop.app.reconcile.apply import apply
from taskloop.app.reconcile.observe import lease_of
from taskloop.contracts.bead import Bead
from taskloop.contracts.beadsport import BeadPatch, NewBead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.slots import SlotGitError
from taskloop.domain.reconcile.facts import (
    Action,
    DeleteBranch,
    DeleteRemote,
    FreeSlot,
    Keep,
    NoLoop,
    ReleaseClaim,
    RemoveTree,
)


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


class Apply(Case):
    def test_each_delete_passes_the_oid_it_was_planned_at(self):
        sh = FakeGit()
        removed, kept = apply([DeleteBranch("/r", "r", "task/a", "abc"), DeleteRemote("/r", "r", "refs/heads/task/a", "def")], False, sh)
        assert sh.calls == [("delete_branch_at", "task/a", "abc"), ("delete_remote_at", "origin", "refs/heads/task/a", "def")]
        assert (len(removed), kept) == (2, [])

    def test_a_moved_branch_stays_with_gits_reason(self):
        removed, kept = apply([DeleteBranch("/r", "r", "task/a", "abc")], False, FakeGit(fail="delete_branch_at"))
        assert (removed, kept) == ([], ["branch task/a (r): fatal: refused"])

    def test_a_branch_stays_when_the_tree_that_held_it_could_not_go(self):
        plan: list[Action] = [RemoveTree("/r", "/b/t", "/b/t"), DeleteBranch("/r", "r", "release/x", "abc", ("/b/t",))]
        sh = FakeGit(fail="remove_worktree_why")
        removed, kept = apply(plan, False, sh)
        assert removed == []
        assert kept[1] == "branch release/x (r): a worktree still has it"
        assert ("delete_branch_at", "release/x", "abc") not in sh.calls

    def test_the_dry_run_runs_nothing(self):
        sh = FakeGit()
        removed, kept = apply([DeleteBranch("/r", "r", "task/a", "abc"), Keep("worktree /w", "this shell is in it")], True, sh)
        assert sh.calls == []
        assert (removed, kept) == (["would remove branch task/a (r)"], ["worktree /w: this shell is in it"])


class Leases(Case):
    def test_a_held_bead_has_a_lease_at_its_fence_generation(self):
        b = Bead(id=BeadId("a-1"), title="", status="in_progress", assignee="tl-x", metadata={"fence_gen": "3"},
                 lease_expires_at="2026-10-30T00:00:00Z")
        ls = lease_of(b, {BeadId("a-1"): "s1"})
        assert ls, "no lease"
        assert (ls.holder, ls.gen, ls.expires, ls.live) == ("tl-x", 3, 1793318400.0, True)
        assert not lease_of(b, {}).live  # type: ignore[union-attr]

    def test_only_a_bead_in_progress_holds_a_lease(self):
        for status, who in (("closed", "x"), ("open", ""), ("blocked", "x")):
            assert lease_of(Bead(id=BeadId("a-1"), title="", status=status, assignee=who), {}) is None
        assert lease_of(Bead(id=BeadId("a-1"), title="slot h s1", status="in_progress", assignee="x", labels=["slot"]), {}) is None


class Given(Case):
    """ReleaseClaim and FreeSlot against a bd in memory: done only while the holder and the generation are the seen ones."""

    def setup_method(self):
        self.store = FakeBeads()
        self.bead = self.store.create(NewBead(title="work"))
        self.slot = self.store.create(NewBead(title="slot h s1", labels=["slot"]))
        for b, key in ((self.bead, "fence_gen"), (self.slot, "held_gen")):
            self.store.update(b, BeadPatch(status="in_progress", assignee="tl-x", set_metadata={key: "2"}))

    def run_plan(self, *plan):
        return apply(list(plan), False, FakeGit(), lambda repo: self.store)

    def test_a_released_claim_is_open_and_unassigned(self):
        removed, kept = self.run_plan(ReleaseClaim("/r", "r", self.bead, "tl-x", 2))
        shown = self.store.show(self.bead)
        assert (len(removed), kept, shown.status, shown.assignee) == (1, [], "open", "")  # type: ignore[union-attr]

    def test_a_retaken_claim_is_left_alone(self):
        self.store.update(self.bead, BeadPatch(set_metadata={"fence_gen": "3"}))
        removed, kept = self.run_plan(ReleaseClaim("/r", "r", self.bead, "tl-x", 2))
        assert (removed, self.store.show(self.bead).assignee) == ([], "tl-x")  # type: ignore[union-attr]
        assert "taken again" in kept[0]

    def test_a_claim_now_another_actors_is_left_alone(self):
        self.store.update(self.bead, BeadPatch(assignee="tl-y"))
        removed, kept = self.run_plan(ReleaseClaim("/r", "r", self.bead, "tl-x", 2))
        assert (removed, self.store.show(self.bead).assignee) == ([], "tl-y")  # type: ignore[union-attr]
        assert "no longer held" in kept[0]

    def test_a_freed_slot_loses_its_marks_and_keeps_its_generation(self):
        self.store.update(self.slot, BeadPatch(set_metadata={"held_by": "tl-x", "held_bead": "a-1"}))
        removed, _ = self.run_plan(FreeSlot("/r", "r", self.slot, "s1", "tl-x", 2))
        shown = self.store.show(self.slot)
        assert len(removed) == 1
        assert (shown.status, shown.assignee, shown.metadata.get("held_by"), shown.metadata.get("held_gen")) == (  # type: ignore[union-attr]
            "open", "", None, "2")

    def test_a_retaken_slot_is_left_alone(self):
        self.store.update(self.slot, BeadPatch(set_metadata={"held_gen": "3"}))
        removed, kept = self.run_plan(FreeSlot("/r", "r", self.slot, "s1", "tl-x", 2))
        assert (removed, self.store.show(self.slot).assignee) == ([], "tl-x")  # type: ignore[union-attr]
        assert "taken again" in kept[0]

    def test_the_dry_run_and_a_finding_change_nothing(self):
        plan: list[Action] = [ReleaseClaim("/r", "r", self.bead, "tl-x", 2), NoLoop("r", 1, 0.0)]
        removed, kept = apply(plan, True, FakeGit(), lambda repo: self.store)
        assert (len(removed), kept, self.store.show(self.bead).assignee) == (1, [], "tl-x")  # type: ignore[union-attr]
