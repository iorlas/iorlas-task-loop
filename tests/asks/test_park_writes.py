"""The asks stage is the one writer of a bead's park: the loop's profile-ahead park and a stage run's finish go through it."""
from pathlib import Path
from random import random

import pytest

from tlkernel import askparks as parks
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import ParkStore
from tlkernel.paths import ConfigDir
from tltestkit.tmpdir import TemporaryDirectory

BEAD = Bead(id=BeadId("t-1"), title="work", status="open")


def test_profile_ahead_files_a_short_park_with_its_reason():
    with TemporaryDirectory() as tmp:
        cfg = ConfigDir(Path(tmp))
        parks.profile_ahead(cfg, BEAD, "run-1", 100.0, "profile_ahead", store=ParkStore)
        rec = ParkStore(cfg).get(BEAD.id)
        assert rec is not None
        assert rec.reason == "profile_ahead"
        assert rec.run == "run-1"
        assert rec.attempts == {"engine:profile_ahead": 1}


def test_finished_drops_the_park():
    with TemporaryDirectory() as tmp:
        cfg = ConfigDir(Path(tmp))
        parks.profile_ahead(cfg, BEAD, "run-1", 100.0, "profile_ahead", store=ParkStore)
        parks.finished(cfg, BEAD.id, store=ParkStore)
        assert ParkStore(cfg).get(BEAD.id) is None



def test_non_pause_has_no_park_wake(workdir):
    with pytest.raises(ValueError, match="no park wake for kind"):
        parks.paused(ConfigDir(workdir), BEAD, Kind.FAULT_INFRA, "run-1", 100.0, store=ParkStore, draw=random)


@pytest.mark.parametrize("permanence", ["needs_owner", "transient"])
def test_delegate_stop_books_its_permanence(workdir, permanence):
    rec = parks.paused(ConfigDir(workdir), BEAD, Kind.PAUSE_ACCOUNT, "run-1", 100.0,
                       producer="delegate", permanence=permanence, draw=lambda: 0.5, store=ParkStore)
    assert rec.permanence == permanence
    assert rec.retry_at == 0.0 if permanence == "needs_owner" else rec.retry_at > 100.0
