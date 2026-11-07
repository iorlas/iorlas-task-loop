"""Stage faults retry under the same slot lease until per-bead escalation parks the bead."""
from unittest.mock import Mock

from taskloop.app.loop.loop import Loop
from taskloop.app.loop.net import NetState
from taskloop.app.loop.settle import Counters, Settle
from taskloop.app.loop.take import Taken
from taskloop.app.loop.verdict import Verdict
from tlasks import parks
from tlkernel import runoutcome as outcome
from tlkernel.bead import Bead
from tlkernel.config import LoopConfig
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import ParkStore
from tlkernel.paths import ConfigDir
from tltestkit.fake_clock import FakeClock


def test_stage_fault_keeps_slot_and_retries_until_parked(workdir):
    clock = FakeClock()
    bead = Bead(id=BeadId("x-1"), title="work", status="open")
    env = Mock(cfgdir=ConfigDir(workdir), now=clock.now)
    loop = Mock(spec=Loop, env=env, c=Counters(), started=clock.now(), prof=Mock(), files=Mock(), taker=Mock())
    loop.prof.slots.count = 1
    loop.acquire.return_value = ("s1", str(workdir), BeadId("slot-1"))
    loop.ends.return_value = None
    loop.settle = Settle(env, loop.files, LoopConfig, Mock(), loop.c, NetState(), Mock())
    loop.settle.candidates = Mock(side_effect=lambda name, beads: beads)
    lease = env.slots.lease.return_value.start.return_value
    fault = outcome.make(Kind.FAULT_BAD_REQUEST, "invalid schema")
    history, attempts = [], []

    def run(cands, at, slots, engine, rule, held):
        assert cands == [bead]
        assert (at.slot, held) == ("s1", lease)
        loop.release.assert_not_called()
        lease.stop.assert_not_called()
        assert loop.c.later == {}
        loop.files.rest_bead.assert_not_called()
        attempts.append(clock.now())
        decision = outcome.apply(fault, bead.id, history, clock.now())
        history.append({"bead": bead.id, "kind": fault.kind.value,
                        "fingerprint": fault.fingerprint, "t": clock.now()})
        parks.ended(env.cfgdir, bead, decision.kind, str(len(history)), clock.now())
        return Taken(Verdict(decision.loop_result, kind=decision.kind.value, run=str(len(history))), bead.id)

    loop.taker.attempt_all.side_effect = run
    assert Loop.work(loop, [bead], Mock()) is None
    assert attempts == [clock.now()] * outcome.KNOBS["fault_retries"]
    assert loop.c.ran == len(attempts)
    assert loop.c.wait is None
    rec = ParkStore(env.cfgdir).get(bead.id)
    assert rec is not None and rec.permanence == "needs_owner"
    loop.acquire.assert_called_once()
    loop.release.assert_called_once_with("s1")
    lease.stop.assert_called_once()
