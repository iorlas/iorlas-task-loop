"""The landing fake records calls and returns configured answers."""
from tlkernel.bead import Bead
from tlkernel.ids import BeadId

from tlland.testing import FakeLandStage


def test_recording_landing_capabilities():
    host = object()
    result = object()
    stage = FakeLandStage(sha="landed", green=False, result=result)
    assert stage(host) is stage
    assert stage.hosts == [host]
    stage.out.wip_push(3)
    assert not stage.gate.green()
    assert stage.gate.run() is result
    bead = Bead(id=BeadId("t-1"), title="test", status="open")
    assert stage.finish(bead) == "landed"
    assert stage.calls == [("wip_push", 3), ("green", None), ("run", None), ("finish", bead)]
