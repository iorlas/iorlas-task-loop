"""The close's steps, each over a small host with just the members its Protocol lists (support/narrow_hosts.py), not an Engine."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.narrow_hosts import CloseKit, FakeReleaseSlotHost, FakeSettleHost

# isort: split
from taskloop.app.run.closer_branch import ReleaseSlot
from taskloop.app.run.closer_settle import Settle
from taskloop.contracts.bead import Bead
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.log import Note
from taskloop.domain import effects as fx
from taskloop.domain import outcome as oc


class Effects(unittest.TestCase):
    def test_a_dry_run_says_so_and_changes_nothing(self):
        kit = CloseKit()
        kit.closer.apply(fx.NoteDry(), oc.make(Kind.DONE), "cost=$0.00")
        (said,) = kit.host.said()
        assert isinstance(said, Note)
        self.assertEqual(said, Note(text="dry run: bead left as it was. cost=$0.00", t=said.t))

    def test_the_slot_is_left_with_the_outcome_and_the_branch(self):
        kit = CloseKit()
        kit.closer.apply(fx.ReleaseSlot(branch="task/t-1", slot_gen=0), oc.make(Kind.DONE), "")
        self.assertEqual(kit.slot.left, [("task/t-1", Outcome.DONE)])

    def test_a_branch_is_saved_with_the_outcome(self):
        kit = CloseKit()
        kit.closer.apply(fx.SaveBranch(), oc.make(Kind.FAULT_INFRA, "x"), "")
        self.assertEqual(kit.calls, ["branch failed"])


class Settling(unittest.TestCase):
    def test_a_pause_lets_the_bead_go_open_and_unassigned(self):
        host = FakeSettleHost(oc.apply(oc.make(Kind.PAUSE_LANE, "the lane is out"), "t-1", [], 1000.0))
        host.store.beads[BeadId("t-1")] = Bead(id=BeadId("t-1"), title="t", status="in_progress", assignee="me")
        rc = Settle(host).leave_open(Kind.PAUSE_LANE, "the lane is out")
        self.assertEqual(rc, 0)
        held = host.store.beads[BeadId("t-1")]
        self.assertEqual((held.status, held.assignee), ("open", ""))
        self.assertEqual(host.warnings, ["the lane is out"])


class Leaving(unittest.TestCase):
    def test_the_slot_is_left_by_its_own_run_only(self):
        host = FakeReleaseSlotHost()
        ReleaseSlot(host).run("task/t-1", Outcome.DONE)
        self.assertEqual(host.tree.left, [("done", "task/t-1")])


if __name__ == "__main__":
    unittest.main()
