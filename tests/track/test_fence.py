"""The fence (app/track/fence.py): a run whose lease was retaken, or a second run on the same bead, cannot close, block, land or write
the checkpoint, and is told why."""
import contextlib
import io
import sys
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.spawn import port_git
from support.who import who

# isort: split
from support.fake_beads import FakeBeads
from support.memstores import fake_stores

from taskloop.app.run.run_once import Ended, RunOnce
from taskloop.app.run.state import Checkpoints
from taskloop.app.track import verbs
from taskloop.app.wire import closeguard
from taskloop.contracts import fence
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdError, BdFailure, BeadPatch

ME = "tl-run00001"
LOCKED = BdFailure(BdError(kind="other", text="locked"))


def world() -> FakeBeads:
    bd = FakeBeads(actor=ME)
    bd.beads[BeadId("x-1")] = Bead(id=BeadId("x-1"), title="work", status="open")
    bd.beads[BeadId("sl-1")] = Bead(id=BeadId("sl-1"), title="slot h s1", status="open", labels=["slot"])
    return bd


def taken(bd: FakeBeads, slot_bead: str = "") -> fence.Claim:
    assert bd.claim(BeadId("x-1"))
    return fence.take(bd, BeadId("x-1"), ME, BeadId(slot_bead))


class Generation(Case):
    def test_every_take_bumps_the_bead_generation(self):
        bd = world()
        first = taken(bd)
        bd.unclaim(BeadId("x-1"))
        second = taken(bd)
        assert (first.gen, second.gen) == (1, 2)
        assert fence.stale(bd, second) == ""
        assert "taken again by another run (generation 2, this run holds 1)" in fence.stale(bd, first)

    def test_only_the_fence_makes_a_claim(self):
        with pytest.raises(TypeError):
            fence.Claim(object(), "x-1", ME, 1, "", 0)  # type: ignore[arg-type]

    def test_a_slot_taken_again_fences_the_run_that_held_it(self):
        bd = world()
        bd.beads[BeadId("sl-1")] = bd.beads[BeadId("sl-1")].replace(metadata={fence.SLOT_GEN: "3"})
        c = taken(bd, "sl-1")
        slot = BeadId("sl-1")
        bd.beads[slot] = bd.beads[slot].replace(metadata={fence.SLOT_GEN: "4"})  # the same actor takes it again: a higher number
        assert "slot bead sl-1 was taken again (generation 4, this run holds 3)" in fence.stale(bd, c)

    def test_a_bead_that_is_not_there_fences_nothing(self):
        bd = world()
        c = taken(bd)
        del bd.beads[BeadId("x-1")]
        assert fence.stale(bd, c) == ""

    def test_a_bd_that_cannot_be_asked_refuses_the_claim(self):
        bd = world()
        c = taken(bd, "sl-1")
        with mock.patch.object(bd, "show", side_effect=LOCKED):
            assert "x-1: ownership unreadable (other: locked)" in fence.stale(bd, c)
            with pytest.raises(fence.Fenced):
                fence.check(bd, c)

    def test_a_slot_that_cannot_be_read_refuses_the_claim(self):
        bd = world()
        c = taken(bd, "sl-1")
        real = bd.show
        with mock.patch.object(bd, "show", side_effect=lambda b: real(b) if b == BeadId("x-1") else (_ for _ in ()).throw(LOCKED)):
            assert "slot bead sl-1: ownership unreadable" in fence.stale(bd, c)

    def test_a_take_that_a_second_run_bumped_at_once_is_refused(self):
        bd = world()
        assert bd.claim(BeadId("x-1"))
        real = bd.update

        def racing(bead, patch):
            real(bead, patch)
            real(bead, BeadPatch(set_metadata={fence.BEAD_GEN: "9"}))  # the other run wrote after ours

        with mock.patch.object(bd, "update", racing), pytest.raises(fence.Fenced, match="taken by another run while this one took it"):
            fence.take(bd, BeadId("x-1"), ME)


class Refused(Case):
    def setup_method(self):
        for name in ("event", "prune_events", "provenance"):  # the trail is a file under the repo: not what is tried here
            self.enterContext(mock.patch.object(verbs, name, lambda *a, **kw: None))
        self.bd = world()
        self.old = taken(self.bd)
        self.bd.unclaim(BeadId("x-1"))
        self.new = taken(self.bd)  # a second run on the same bead, same actor

    def err(self, call):
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = call()
        return rc, buf.getvalue()

    def test_close_by_the_stale_run_is_refused_and_says_why(self):
        rc, err = self.err(lambda: verbs.close_as(who(), self.old, "merged", self.bd, closeguard.ENGINE))
        assert rc == 1
        assert "fenced: x-1 not closed" in err
        assert "generation 2, this run holds 1" in err
        assert self.bd.beads[BeadId("x-1")].status == "in_progress"
        assert verbs.close_as(who(), self.new, "merged", self.bd, closeguard.ENGINE) == 0
        assert self.bd.beads[BeadId("x-1")].status == "closed"

    def test_block_by_the_stale_run_is_refused(self):
        rc, err = self.err(lambda: verbs.block_as(who(), self.old, "stuck", self.bd))
        assert rc == 1
        assert "fenced: x-1 not blocked" in err
        assert self.bd.beads[BeadId("x-1")].status == "in_progress"

    def test_land_by_the_stale_run_records_nothing(self):
        rc, err = self.err(lambda: verbs.land(who(), BeadId("x-1"), "abc123", self.bd, port_git(), claim=self.old))
        assert rc == 1
        assert "fenced: land of x-1 not recorded" in err

    def test_the_checkpoint_of_the_stale_run_is_not_written(self):
        stores = fake_stores()
        host = SimpleNamespace(bead="x-1", stores=stores, store=self.bd, claim=self.old)
        ck = Checkpoints(host)
        with pytest.raises(fence.Fenced) as cm:
            ck.writer()
        assert "taken again" in cm.value.why
        host.claim = self.new
        assert ck.writer() is ck.doc

    def test_a_close_sends_the_assignee_guard_and_a_changed_assignee_refuses_it(self):
        self.bd.beads[BeadId("x-1")] = self.bd.beads[BeadId("x-1")].replace(assignee="tl-other")  # the claim changed hands
        rc, err = self.err(lambda: verbs.close_as(who(), self.new, "merged", self.bd, closeguard.ENGINE))
        assert (rc, self.bd.beads[BeadId("x-1")].status) == (1, "in_progress")
        assert "assignee changed" in err

    def test_a_fenced_run_closes_nothing_and_says_it_was_fenced_out(self):
        warned, closed = [], []
        host = SimpleNamespace(moved=False, stop_deferred=contextlib.nullcontext, landed_sha="", fenced="", store=self.bd, claim=self.old,
                               warn=warned.append, closer=SimpleNamespace(close=lambda *a: closed.append(a)),
                               records=SimpleNamespace(settle=lambda *a: None))
        hb = mock.Mock()
        RunOnce(host).close_out(hb, Ended())
        assert closed == []
        assert "fenced out" in warned[0]
        assert "taken again by another run" in host.fenced
        assert self.bd.beads[BeadId("x-1")].status == "in_progress"
