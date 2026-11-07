"""The asks stage is the one writer of a bead's park: the loop's profile-ahead park and a stage run's finish go through it."""
from pathlib import Path

import support.paths  # noqa: F401
from support.tmpdir import TemporaryDirectory

from taskloop.app.asks import parks
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.parks import ParkStore
from tlkernel.paths import ConfigDir

BEAD = Bead(id=BeadId("t-1"), title="work", status="open")


def test_profile_ahead_files_a_short_park_with_its_reason():
    with TemporaryDirectory() as tmp:
        cfg = ConfigDir(Path(tmp))
        parks.profile_ahead(cfg, BEAD, "run-1", 100.0, "profile_ahead")
        rec = ParkStore(cfg).get(BEAD.id)
        assert rec is not None
        assert rec.reason == "profile_ahead"
        assert rec.run == "run-1"
        assert rec.attempts == {"engine:profile_ahead": 1}


def test_finished_drops_the_park():
    with TemporaryDirectory() as tmp:
        cfg = ConfigDir(Path(tmp))
        parks.profile_ahead(cfg, BEAD, "run-1", 100.0, "profile_ahead")
        parks.finished(cfg, BEAD.id)
        assert ParkStore(cfg).get(BEAD.id) is None
