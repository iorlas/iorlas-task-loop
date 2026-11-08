"""Flake persistence and repair filing use memory stores and fake beads."""
import pytest
from support.fake_beads import FakeBeads

from tlkernel.bead import BdError
from tlkernel.beadsport import BdFailure, NewBead
from tlkernel.flakes import FlakeLog, FlakeRow
from tlkernel.ids import BeadId
from tlland.flake_book import FlakeBook
from tltestkit.memdoc import MemDoc

NOW = 40 * 86400.0


def flake(test: str = "test_a", t: float = NOW) -> FlakeRow:
    return FlakeRow(test=test, t=t, how="retry")


def test_fourth_files_once_and_closed_bead_allows_another():
    doc = MemDoc(FlakeLog)
    beads = FakeBeads()
    book = FlakeBook(doc, beads, lambda: NOW)
    for _ in range(3):
        assert book.record(flake()) is None
    escalation = book.record(flake())
    assert escalation is not None and escalation.count == 4
    log = doc.need()
    assert log is not None
    bead_id = BeadId(log.rows[-1].bead)
    bead = beads.show(bead_id)
    assert bead is not None
    assert bead.title == "Fix flaky test test_a"
    assert bead.labels == ["auto"]
    assert not bead.parent
    assert "4" in bead.description and "week" in bead.description
    assert "stays in the gate" in bead.description
    assert book.record(flake()) is None
    assert len(beads.ready()) == 1
    beads.close(bead_id, "fixed")
    assert book.record(flake()) is not None
    log = doc.need()
    assert log is not None and log.rows[-1].bead != str(bead_id)
    assert len(beads.ready()) == 1


def test_old_rows_are_dropped_including_an_old_incoming_row():
    doc = MemDoc(FlakeLog)
    boundary = NOW - 30 * 86400
    doc.write(FlakeLog(rows=[flake(t=boundary - 1), flake(t=boundary)]))
    book = FlakeBook(doc, FakeBeads(), lambda: NOW)
    assert book.record(flake()) is None
    assert doc.need() == FlakeLog(rows=[flake(t=boundary), flake()])
    assert book.record(flake(t=boundary - 1)) is None
    assert doc.need() == FlakeLog(rows=[flake(t=boundary), flake()])


class FailingBeads(FakeBeads):
    def create(self, new: NewBead) -> BeadId:
        raise BdFailure(BdError(kind="other", text="create failed"))


def test_failed_create_keeps_the_fourth_row():
    doc = MemDoc(FlakeLog)
    doc.write(FlakeLog(rows=[flake()] * 3))
    book = FlakeBook(doc, FailingBeads(), lambda: NOW)
    with pytest.raises(BdFailure, match="create failed"):
        book.record(flake())
    assert doc.need() == FlakeLog(rows=[flake()] * 4)


def test_tests_are_counted_separately():
    doc = MemDoc(FlakeLog)
    beads = FakeBeads()
    book = FlakeBook(doc, beads, lambda: NOW)
    for _ in range(3):
        assert book.record(flake("a")) is None
        assert book.record(flake("b")) is None
    escalation = book.record(flake("a"))
    assert escalation is not None and escalation.count == 4
    assert len(beads.ready()) == 1
    escalation = book.record(flake("b"))
    assert escalation is not None and escalation.count == 4
    assert len(beads.ready()) == 2


def test_rows_outside_the_week_do_not_trigger_filing():
    doc = MemDoc(FlakeLog)
    doc.write(FlakeLog(rows=[flake(t=NOW - 7 * 86400 - 1)] * 3))
    assert FlakeBook(doc, FakeBeads(), lambda: NOW).record(flake()) is None
