"""The close's effects over a small host (just the members app/run/closer_host.py CloserHost lists), not an Engine."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.narrow_hosts import FakeWaitsHost

# isort: split
from taskloop.app.run.closer import Closer
from taskloop.contracts import fence
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import BeadId
from taskloop.contracts.log import Note
from taskloop.domain import effects as fx
from taskloop.domain import outcome as oc


def host(kind: oc.Kind) -> tuple[SimpleNamespace, FakeWaitsHost]:
    """A host that has what these effects read; its log is the fake waits host's (in memory), its bd a recorder."""
    base = FakeWaitsHost()
    done = oc.make(kind, "the lane is out")
    e = SimpleNamespace(
        bead=BeadId("t-1"), claim=fence.offline(BeadId("t-1")), dry=True, log=base.log, warn=mock.Mock(), comment=mock.Mock(),
        store=mock.Mock(), tree=mock.Mock(), disp=oc.apply(done, "t-1", [], 1000.0), branch="")
    return e, base


class Effects(unittest.TestCase):
    def test_a_dry_run_says_so_and_changes_nothing(self):
        e, base = host(oc.Kind.DONE)
        Closer(e).apply(fx.NoteDry(), oc.make(oc.Kind.DONE), "cost=$0.00")
        said = base.stores.run_log("run").read_from(0).items[0].rec
        self.assertEqual(said, Note(text="dry run: bead left as it was. cost=$0.00", t=said.t))
        e.store.update.assert_not_called()

    def test_a_pause_lets_the_bead_go_open_and_unassigned(self):
        e, _ = host(oc.Kind.PAUSE_LANE)
        rc = Closer(e).leave_open(oc.Kind.PAUSE_LANE, "the lane is out")
        self.assertEqual(rc, 0)
        patch = e.store.update.call_args.args[1]
        self.assertEqual((patch.status, patch.assignee), ("open", ""))
        e.warn.assert_called_once_with("the lane is out")

    def test_the_slot_is_left_with_the_outcome_and_the_branch(self):
        e, _ = host(oc.Kind.DONE)
        Closer(e).apply(fx.ReleaseSlot(branch="task/t-1", slot_gen=0), oc.make(oc.Kind.DONE), "")
        e.tree.leave_slot.assert_called_once_with(Outcome.DONE, "task/t-1")


if __name__ == "__main__":
    unittest.main()
