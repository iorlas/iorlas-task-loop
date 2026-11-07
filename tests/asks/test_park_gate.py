"""The park gate on a bead the owner parked: the owner's hold decides, and the gate answers instead of failing."""
from pathlib import Path

from taskloop.app.wire import asks as asks_wire
from tlkernel import askparks as parks
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import Park, ParkStore
from tlkernel.paths import ConfigDir
from tltestkit.tmpdir import TemporaryDirectory


def test_an_owner_park_with_no_hold_is_released_by_the_gate():
    with TemporaryDirectory() as tmp:
        cfg = ConfigDir(Path(tmp))
        bead = Bead(id=BeadId("t-1"), title="work", status="open")
        ParkStore(cfg).put(Park(bead=bead.id, hash="h", runs=1, run="r", t=1.0, reason=Kind.OWNER_PARK.value))
        assert parks.gate(asks_wire.host().asks_store(cfg), cfg, bead, now=2.0, store=ParkStore) is None
