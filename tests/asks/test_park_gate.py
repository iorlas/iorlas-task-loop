"""The park gate on a bead the owner parked: the owner's hold decides, and the gate answers instead of failing."""
from pathlib import Path

import support.paths  # noqa: F401
from support.tmpdir import TemporaryDirectory

from taskloop.app.asks import parks
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import Park, ParkStore
from taskloop.contracts.paths import ConfigDir


def test_an_owner_park_with_no_hold_is_released_by_the_gate():
    with TemporaryDirectory() as tmp:
        cfg = ConfigDir(Path(tmp))
        bead = Bead(id=BeadId("t-1"), title="work", status="open")
        ParkStore(cfg).put(Park(bead=bead.id, hash="h", runs=1, run="r", t=1.0, reason=Kind.OWNER_PARK.value))
        assert parks.gate(cfg, bead, now=2.0) is None
