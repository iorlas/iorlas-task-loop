"""CRASHMATRIX slice 3: an effect killed halfway runs again (the interpreter writes a key only after the effect returned), so every
effect must be safe to repeat. The effects that act on the bead are applied twice over a bd in memory and must leave the bead as the
first application did; every other effect is named in NOT_HERE with where its repeat is covered, so a new effect cannot be added
without saying how its repeat is safe."""
import dataclasses
import typing

import pytest
from support.narrow_hosts import FakeSettleHost

from taskloop.adapters import beadtools
from taskloop.app.track.closing import ClosingBeads
from taskloop.app.wire import closeguard
from tlkernel import askspecs
from tlkernel import closeeffects as fx
from tlkernel import runoutcome as oc
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlpipeline.api import Settle
from tlpipeline.testing import FakeParkBook

# effect class -> the outcome whose settling it is. One case per kind of settling the plan can end in.
SETTLING = {
    "close landed": (fx.CloseBead, oc.make(Kind.LANDED, "landed", sha="abcdef123456")),
    "close done": (fx.CloseBead, oc.make(Kind.DONE, "done")),
    "block on the owner": (fx.BlockBead, oc.make(Kind.ASK_STUCK, "the task is wrong", spec=askspecs.repeated_fault(3, "it fails"))),
    "leave open after a machine fault": (fx.LeaveBead, oc.make(Kind.FAULT_INFRA, "disk full")),
    "leave open after a pause": (fx.LeaveBead, oc.make(Kind.PAUSE_LANE, "the lane is out")),
}
NOT_HERE = {
    fx.SaveBranch: "closing_branch: the wip commit of a clean tree is no commit (tests/pipeline/test_closing_branch.py)",
    fx.RecordRun: "a no-op: finish_run already projected the answer (closing.apply)",
    fx.NoteDry: "a log note",
    fx.NoteWait: "a log note",
    fx.RaiseAsk: "the ask store keeps one ask per bead (tests/asks)",
    fx.FileNotes: "the notes are kept in the checkpoint and filed once (closing_notes)",
    fx.Reflect: "the comment is deduped per (bead, kind, fingerprint) per hour",
    fx.ReleaseSlot: "leaves the slot only while its generation is the lease's (closing_branch.ReleaseSlot)",
    fx.DropCheckpoint: "dropping a dropped checkpoint is a no-op",
    fx.RecordLand: "the landed store keys by sha",
    fx.BdSync: "bd sync of nothing new is a no-op",
}


def bead_state(host: FakeSettleHost) -> dict[str, tuple[str, str, tuple[str, ...], str]]:
    return {str(k): (b.status, b.assignee, tuple(sorted(b.labels)), b.close_reason) for k, b in host.store.beads.items()}


def held_host(done: oc.RunOutcome) -> FakeSettleHost:
    host = FakeSettleHost(oc.apply(done, "t-1", [], 1000.0))
    host.store.beads[BeadId("t-1")] = Bead(id=BeadId("t-1"), title="t", status="in_progress", assignee=host.claim.actor)
    return host


@pytest.mark.parametrize("case", SETTLING)
def test_settling_the_bead_twice_leaves_it_as_the_first_time_did(case, monkeypatch):
    monkeypatch.setattr("taskloop.app.track.verbs.event", lambda *args, **kwargs: None)
    monkeypatch.setattr("taskloop.app.track.verbs.prune_events", lambda *args: None)
    monkeypatch.setattr("taskloop.app.track.verbs.provenance", lambda *args, **kwargs: None)
    cls, done = SETTLING[case]
    host = held_host(done)
    before = bead_state(host)
    Settle(host, ClosingBeads(host.who, host.store, closeguard.ENGINE), FakeParkBook(), beadtools.peek, beadtools.attempt).run(done, "")
    first = bead_state(host)
    assert first != before  # the first application did something, or the repeat proves nothing
    Settle(host, ClosingBeads(host.who, host.store, closeguard.ENGINE), FakeParkBook(), beadtools.peek, beadtools.attempt).run(done, "")
    assert bead_state(host) == first
    assert fx.settling(done).__class__ is cls


def test_every_effect_is_either_applied_twice_here_or_named_with_why_its_repeat_is_safe():
    effects = set(typing.get_args(fx.CloseEffect)) | set(typing.get_args(fx.LandEffect))
    here = {cls for cls, _ in SETTLING.values()}
    assert effects == here | set(NOT_HERE), "a new effect: add it to SETTLING or to NOT_HERE with why it is safe to repeat"
    assert all(dataclasses.is_dataclass(c) for c in effects)
