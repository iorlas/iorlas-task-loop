"""The lease rules the loop's step and the run entry share (app/reconcile/leases.py `release_dead`): every case the retired `loop.reclaim`
(bd reclaim) and `entry.reclaim` released is a row here, run through the one rule."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads

from taskloop.app.reconcile.leases import release_dead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BeadPatch, NewBead

ENDED, RUNNING = "2000-01-01T00:00:00Z", "2999-01-01T00:00:00Z"


class ReleaseDead(unittest.TestCase):
    def setUp(self):
        self.store = FakeBeads()

    def bead(self, status="in_progress", who="tl-dead", ends=ENDED, title="work", labels=(), **meta: str) -> BeadId:
        b = self.store.create(NewBead(title=title, labels=list(labels)))
        self.store.update(b, BeadPatch(status=status, assignee=who, set_metadata={"fence_gen": "3", **meta}))
        self.store._put(self.store.beads[b], lease_expires_at=ends)
        return b

    def sweep(self, live=None):
        return release_dead("/r/repo", self.store, live or {}, "host", time.time())

    def held(self, b: BeadId):
        x = self.store.show(b)
        return x.status, x.assignee  # type: ignore[union-attr]

    def test_a_dead_engine_claim_whose_lease_ended_goes_back(self):
        b = self.bead()
        self.assertEqual(len(self.sweep()), 1)
        self.assertEqual(self.held(b), ("open", ""))
        self.assertEqual(self.sweep(), [])  # a second sweep finds nothing

    def test_a_paused_run_leaves_the_bead_open_and_assigned_and_it_goes_back_when_the_lease_ended(self):
        b = self.bead(status="open")
        self.sweep()
        self.assertEqual(self.held(b), ("open", ""))

    def test_a_claim_with_no_lease_goes_back(self):
        b = self.bead(ends="")
        self.sweep()
        self.assertEqual(self.held(b), ("open", ""))

    def test_a_claim_inside_its_lease_stays(self):
        b = self.bead(ends=RUNNING)
        self.assertEqual(self.sweep(), [])
        self.assertEqual(self.held(b), ("in_progress", "tl-dead"))

    def test_a_claim_with_a_live_run_stays_past_its_lease(self):
        b = self.bead()
        self.assertEqual(self.sweep({b: "s1"}), [])

    def test_a_persons_claim_is_never_given_back(self):
        b = self.bead(who="denis")
        self.assertEqual(self.sweep(), [])
        self.assertEqual(self.held(b), ("in_progress", "denis"))

    def test_a_blocked_bead_keeps_its_status_and_assignee(self):
        b = self.bead(status="blocked")
        self.assertEqual(self.sweep(), [])
        self.assertEqual(self.held(b), ("blocked", "tl-dead"))

    def test_a_claim_the_loop_left_for_another_bead_goes_back_inside_its_lease(self):
        left, other = self.bead(ends=RUNNING, who="tl-loop"), self.bead(ends=RUNNING, who="tl-loop")
        slot = self.bead(ends=RUNNING, who="tl-loop", title="slot host s5", labels=["slot"], held_bead=other)
        self.assertEqual(len(self.sweep({other: "s5"})), 1)
        self.assertEqual(self.held(left), ("open", ""))
        self.assertEqual(self.held(other), ("in_progress", "tl-loop"))
        self.assertEqual(self.held(slot), ("in_progress", "tl-loop"))

    def test_the_loop_running_this_very_bead_keeps_its_claim(self):
        b = self.bead(ends=RUNNING, who="tl-loop")
        self.bead(ends=RUNNING, who="tl-loop", title="slot host s5", labels=["slot"], held_bead=b)
        self.assertEqual(self.sweep(), [])  # the slot says it, the engine is just starting

    def test_a_dead_loops_slot_is_freed_and_its_marks_cleared(self):
        slot = self.bead(who="tl-loop", title="slot host s5", labels=["slot"], held_bead="x-1", held_by="tl-loop")
        self.assertEqual(len(self.sweep()), 1)
        x = self.store.show(slot)
        self.assertEqual((x.status, x.assignee), ("open", ""))  # type: ignore[union-attr]
        self.assertNotIn("held_by", x.metadata)  # type: ignore[union-attr]

    def test_a_claim_that_changed_hands_after_the_look_stays(self):
        b = self.bead()
        real = self.store.update

        def retaken(bead, patch):  # another run takes it between the sweep's look and its write
            self.store._put(self.store.beads[b], assignee="tl-new", lease_expires_at=RUNNING)
            return real(bead, patch)

        self.store.update = retaken  # type: ignore[method-assign]
        self.assertEqual(self.sweep(), [])
        self.assertEqual(self.held(b), ("in_progress", "tl-new"))


if __name__ == "__main__":
    unittest.main()
