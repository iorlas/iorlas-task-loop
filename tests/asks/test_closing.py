"""Closing asks uses the stage's validation and persistent park transitions."""
from dataclasses import replace
from pathlib import Path

import pytest

from taskloop.app.asks import raiser
from taskloop.app.asks.closing import ClosingAsks
from taskloop.domain.asks.spec import AskSpec
from tlkernel.ask import AskOption
from tlkernel.askenums import AskClass
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import ParkStore
from tlkernel.paths import ConfigDir


@pytest.mark.parametrize("valid", [True, False])
def test_problems_matches_raiser(workdir: Path, valid: bool):
    spec = AskSpec(ask_class=AskClass.OPEN_QUESTION, decision="Should we proceed?", options=[
        AskOption(label="Proceed", consequence="The run continues.", recommended=True),
        AskOption(label="Stop", consequence="The work stays paused."),
    ])
    if not valid:
        spec = replace(spec, decision="")
    result = ClosingAsks(ConfigDir(workdir)).problems(spec)
    assert result == raiser.problems(spec)
    assert bool(result) is not valid


def test_paused_then_ended_uses_park_store(workdir: Path):
    cfg = ConfigDir(workdir)
    bead = Bead(id=BeadId("t-1"), title="work", status="open")
    closing = ClosingAsks(cfg)
    parked = closing.paused(bead, Kind.PAUSE_NETWORK, "run-1", 1.0,
                            reason="network", not_before=100.0, fingerprint="network-1",
                            producer="delegate", permanence="transient")
    assert parked is not None
    assert ParkStore(cfg).get(bead.id) == parked
    assert parked.reason == "network"
    assert parked.retry_at >= 100.0
    closing.ended(bead, Kind.DONE, "run-1", 2.0)
    assert ParkStore(cfg).get(bead.id) is None
