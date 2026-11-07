"""Closing beads forwards the bound actor, store and guard to the tracking verbs."""
from pathlib import Path

import pytest
from support.fake_beads import FakeBeads

from taskloop.app.track import verbs
from taskloop.app.track.closing import ClosingBeads
from tlkernel import fence
from tlkernel.bead import Bead
from tlkernel.beadsport import BeadPatch
from tlkernel.identity import Identity
from tlkernel.ids import BeadId


class RecordingBeads(FakeBeads):
    def __init__(self) -> None:
        super().__init__()
        self.closed: list[tuple[BeadId, str, str]] = []
        self.updated: list[tuple[BeadId, BeadPatch]] = []

    def close(self, bead: BeadId, reason: str, if_assignee: str = "") -> None:
        self.closed.append((bead, reason, if_assignee))
        super().close(bead, reason, if_assignee)

    def update(self, bead: BeadId, patch: BeadPatch) -> None:
        self.updated.append((bead, patch))
        super().update(bead, patch)


@pytest.mark.parametrize("reason", [None, "merged"])
def test_close_delegates(workdir: Path, monkeypatch: pytest.MonkeyPatch, reason: str | None):
    monkeypatch.setattr(verbs, "event", lambda *args, **kwargs: None)
    monkeypatch.setattr(verbs, "prune_events", lambda *args: None)
    store = RecordingBeads()
    bead = BeadId("t-1")
    store.beads[bead] = Bead(id=bead, title="work", status="open", assignee="person")
    claim = fence.hand(store, bead, "person")
    checked: list[tuple[BeadId, str]] = []

    def guard(bead: BeadId, reason: str) -> str:
        checked.append((bead, reason))
        return ""

    closing = ClosingBeads(Identity(actor="person", home=str(workdir)), store, guard)
    assert closing.close(claim, reason) == 0
    assert checked == [(bead, reason or "done")]
    assert store.closed == [(bead, reason or "done", "person")]


def test_block_delegates(workdir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(verbs, "event", lambda *args, **kwargs: None)
    monkeypatch.setattr(verbs, "provenance", lambda *args, **kwargs: None)
    store = RecordingBeads()
    bead = BeadId("t-1")
    store.beads[bead] = Bead(id=bead, title="work", status="open", assignee="tl-run")
    claim = fence.hand(store, bead, "tl-run")
    said: list[str] = []
    closing = ClosingBeads(Identity(actor="tl-run", home=str(workdir)), store, lambda bead, reason: "")
    assert closing.block(claim, "needs input", said.append) == 0
    assert store.updated == [(bead, BeadPatch(status="blocked", if_assignee="tl-run", assignee=""))]
    assert said == ["Blocked: needs input"]
