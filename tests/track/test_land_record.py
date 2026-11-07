"""BEADMETA: `verbs.land` writes the landed record into the bead's metadata, once the sha is on the base; readers get it back from the
bead (landed_by) and nothing is written to a landed/ file."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.case import Case
from support.who import who

from taskloop.app.track import verbs
from tlkernel.bead import BdError, Bead
from tlkernel.beadsport import BdFailure, BeadPatch
from tlkernel.ids import BeadId
from tlkernel.landed import LANDED_SHA, landed_by, landed_in, landed_meta

BEAD = BeadId("x-1")


class Store:
    """The two calls of the Beads port the land touches, over one bead's metadata."""

    def __init__(self) -> None:
        self.metadata: dict[str, str] = {}
        self.patches: list[BeadPatch] = []

    def provenance(self, *args: object) -> None:
        pass

    def update(self, bead: BeadId, patch: BeadPatch) -> None:
        self.patches.append(patch)
        self.metadata.update(patch.set_metadata)

    def show(self, bead: BeadId) -> Bead:
        return Bead(id=bead, title="t", status="open", metadata=dict(self.metadata))


def git(on_base: bool) -> mock.Mock:
    g = mock.Mock()
    g.rev_parse.return_value = "f" * 40
    g.is_ancestor.return_value = on_base
    return g


class LandRecord(Case):
    def test_a_land_on_the_base_is_written_to_the_bead_and_read_back(self) -> None:
        store = Store()
        assert verbs.land(who(), BEAD, "abc", store, git(True), "/w", base="origin/main") == 0  # type: ignore[arg-type]
        rec = landed_by(store)(BEAD)  # type: ignore[arg-type]
        assert rec is not None
        assert (rec.sha, rec.base) == ("f" * 40, "origin/main")
        assert rec.t > 0

    def test_a_sha_that_is_not_on_the_base_writes_nothing(self) -> None:
        store = Store()
        assert verbs.land(who(), BEAD, "abc", store, git(False), "/w", base="origin/main") == 1  # type: ignore[arg-type]
        assert store.patches == []
        assert landed_by(store)(BEAD) is None  # type: ignore[arg-type]

    def test_the_keys_round_trip_and_a_half_written_record_is_none(self) -> None:
        meta = landed_meta(landed_by(self.stored())(BEAD))  # type: ignore[arg-type]
        assert landed_in(BEAD, meta) is not None
        assert landed_in(BEAD, {LANDED_SHA: "abc"}) is None
        assert landed_in(BEAD, {**meta, "landed_at": "not a time"}) is None
        assert landed_in(BEAD, {}) is None

    def test_a_tracker_that_does_not_answer_is_no_record_not_a_crash(self) -> None:
        down = mock.Mock()
        down.show.side_effect = BdFailure(BdError(kind="other", text="bd is down"))
        assert landed_by(down)(BEAD) is None

    def stored(self) -> Store:
        store = Store()
        verbs.land(who(), BEAD, "abc", store, git(True), "/w", base="origin/main")  # type: ignore[arg-type]
        return store
