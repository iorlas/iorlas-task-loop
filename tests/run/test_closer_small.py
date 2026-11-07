"""The close's steps, each over a small host with just the members its Protocol lists (support/narrow_hosts.py), not an Engine."""
import sys
from pathlib import Path
from unittest import mock

from taskloop.adapters import beadtools
from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.narrow_hosts import CloseKit, FakeReleaseSlotHost, FakeSettleHost

from tlpipeline.testing import FakeParkBook

# isort: split
from taskloop.app.asks import raiser
from taskloop.app.track.closing import ClosingBeads
from taskloop.app.wire import closeguard
from tlkernel import askspecs
from tlkernel import closeeffects as fx
from tlkernel import runoutcome as oc
from tlkernel.bead import Bead
from tlkernel.enums import Outcome
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.log import Note
from tlpipeline.api import ReleaseSlot, Settle
from tlpipeline.testing import FakeLandCleanup


class Effects(Case):
    def test_noop_files_the_owner_ask_through_the_close_effect(self):
        kit = CloseKit()
        kit.host.plan_summary = "An umbrella with existing children"
        with mock.patch.object(kit.host.ask_flow, "raise_ask", return_value=object()) as ask:
            kit.closer.apply(fx.RaiseAsk(), oc.make(Kind.NOOP, "noop"), "")
        ask.assert_called_once_with(askspecs.plan_noop("t-1", kit.host.plan_summary), "noop", Kind.NOOP)
        assert kit.host.asked
        spec = ask.call_args.args[0]
        assert raiser.problems(spec) == []
        assert spec.detail.text == ("The plan finds nothing to implement for t-1: An umbrella with existing children. "
                         "Close it, or give it work.")

    def test_a_dry_run_says_so_and_changes_nothing(self):
        kit = CloseKit()
        kit.closer.apply(fx.NoteDry(), oc.make(Kind.DONE), "cost=$0.00")
        (said,) = kit.host.said()
        assert isinstance(said, Note)
        assert said == Note(text="dry run: bead left as it was. cost=$0.00", t=said.t)

    def test_the_slot_is_left_with_the_outcome_and_the_branch(self):
        kit = CloseKit()
        kit.closer.apply(fx.ReleaseSlot(branch="task/t-1", slot_gen=0), oc.make(Kind.DONE), "")
        assert kit.slot.left == [("task/t-1", Outcome.DONE)]

    def test_a_branch_is_saved_with_the_outcome(self):
        kit = CloseKit()
        kit.closer.apply(fx.SaveBranch(), oc.make(Kind.FAULT_INFRA, "x"), "")
        assert kit.calls == ["branch failed"]


class Settling(Case):
    def test_noop_reopens_and_releases_the_bead(self):
        done = oc.make(Kind.NOOP, "noop: the plan found nothing to implement: umbrella")
        host = FakeSettleHost(oc.apply(done, "t-1", [], 1000.0))
        host.store.beads[BeadId("t-1")] = Bead(id=BeadId("t-1"), title="t", status="in_progress", assignee="me")
        assert Settle(host, ClosingBeads(host.who, host.store, closeguard.ENGINE), FakeParkBook(),
            beadtools.peek, beadtools.attempt).leave_open(done.kind, done.detail) == 0
        held = host.store.beads[BeadId("t-1")]
        assert (held.status, held.assignee) == ("open", "")

    def test_a_pause_lets_the_bead_go_open_and_unassigned(self):
        host = FakeSettleHost(oc.apply(oc.make(Kind.PAUSE_LANE, "the lane is out"), "t-1", [], 1000.0))
        host.store.beads[BeadId("t-1")] = Bead(id=BeadId("t-1"), title="t", status="in_progress", assignee="me")
        settling = Settle(host, ClosingBeads(host.who, host.store, closeguard.ENGINE), FakeParkBook(), beadtools.peek, beadtools.attempt)
        rc = settling.leave_open(Kind.PAUSE_LANE, "the lane is out")
        assert rc == 0
        held = host.store.beads[BeadId("t-1")]
        assert (held.status, held.assignee) == ("open", "")
        assert host.warnings == ["the lane is out"]


class Leaving(Case):
    def test_the_slot_is_left_by_its_own_run_only(self):
        host = FakeReleaseSlotHost()
        ReleaseSlot(host, host.tree, FakeLandCleanup()).run("task/t-1", Outcome.DONE)
        assert host.tree.left == [("done", "task/t-1")]
