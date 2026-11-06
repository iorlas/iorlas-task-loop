"""A sweep over a real repo: a slot (and a claimed bead) whose lease ended with no live run is given back; one retaken between the look
and the write is left alone."""
import sys
import time
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support import homes
from support.fake_beads import FakeBeads

from prune.real.test_prune import git
from taskloop.adapters.git import RealGit
from taskloop.app.reconcile.apply import apply
from taskloop.app.reconcile.observe import observe
from taskloop.contracts.env import snapshot
from taskloop.contracts.ports import BeadPatch, NewBead
from taskloop.domain.reconcile.diff import diff
from taskloop.domain.reconcile.facts import FreeSlot, ReleaseClaim

ENDED = "2000-01-01T00:00:00Z"


class Strays(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        git(tmp.name, "init", "-q", "-b", "main", str(self.repo))
        (self.repo / "f").write_text("x")
        git(self.repo, "add", "f")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "-m", "base")
        self.store = FakeBeads()
        self.slot = self.store.create(NewBead(title="slot host s1", labels=["slot"]))
        self.work = self.store.create(NewBead(title="work"))
        for b, key in ((self.slot, "held_gen"), (self.work, "fence_gen")):
            self.store.update(b, BeadPatch(status="in_progress", assignee="tl-dead", set_metadata={key: "5"}))
            self.store._put(self.store.beads[b], lease_expires_at=ENDED)
        self.store.update(self.slot, BeadPatch(set_metadata={"held_by": "tl-dead", "held_bead": self.work}))

    def plan(self, live=None):
        seen = observe(
            [str(self.repo)], lambda r: self.store, None, 14, time.time(), RealGit(snapshot()), homes.cfg(), lambda r: live or {}, "host"
        )
        return diff(seen)

    def test_a_stray_slot_and_its_dead_claim_are_given_back(self):
        plan = self.plan()
        assert [type(a) for a in plan] == [ReleaseClaim, FreeSlot]
        removed, kept = apply(plan, False, RealGit(snapshot()), lambda r: self.store)
        assert (len(removed), kept) == (2, [])
        slot, work = self.store.show(self.slot), self.store.show(self.work)
        assert (slot.status, slot.assignee, work.status, work.assignee) == ("open", "", "open", "")  # type: ignore[union-attr]
        assert "held_by" not in slot.metadata  # type: ignore[union-attr]
        assert slot.metadata["held_gen"] == "5"  # type: ignore[union-attr]
        assert self.plan() == []  # a second sweep finds nothing

    def test_a_live_run_keeps_both(self):
        assert self.plan({self.work: "s1"}) == []

    def test_a_slot_and_claim_retaken_after_the_look_are_left_alone(self):
        plan = self.plan()
        for b, key in ((self.slot, "held_gen"), (self.work, "fence_gen")):  # a new run takes them under the same actor
            self.store.update(b, BeadPatch(set_metadata={key: "6"}))
        removed, kept = apply(plan, False, RealGit(snapshot()), lambda r: self.store)
        assert removed == []
        assert all("taken again" in k for k in kept) and len(kept) == 2
        assert (self.store.show(self.slot).assignee, self.store.show(self.work).assignee) == ("tl-dead", "tl-dead")  # type: ignore[union-attr]

    def test_a_slot_retaken_by_another_actor_is_left_alone(self):
        plan = self.plan()
        self.store.update(self.slot, BeadPatch(assignee="tl-new", set_metadata={"held_gen": "6"}))
        removed, kept = apply([a for a in plan if isinstance(a, FreeSlot)], False, RealGit(snapshot()), lambda r: self.store)
        assert (removed, self.store.show(self.slot).assignee) == ([], "tl-new")  # type: ignore[union-attr]
        assert "no longer held" in kept[0]
