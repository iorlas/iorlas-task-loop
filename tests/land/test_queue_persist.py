"""Queue persistence preserves every planner phase and build identity."""
import pytest

from taskloop.domain.land.queue_model import Entry, Phase
from taskloop.domain.land.queue_persist import from_doc, to_doc
from taskloop.domain.land.queue_reconcile import BuildFact
from tlkernel.queue_doc import EntryRow, QueueDoc


@pytest.mark.parametrize("phase", list(Phase))
@pytest.mark.parametrize("has_build", [False, True])
def test_round_trip(phase: Phase, has_build: bool):
    entries = [Entry(branch="topic", head="head", phase=phase, q="q", tree="tree", ref="ref", reason="reason", after="first"),
               Entry(branch="other", head="other-head")]
    builds = {"topic": BuildFact("topic", 42, "start", 123.5, "build-dir")} if has_build else {}
    doc = to_doc(entries, builds, in_flight=3, last_base="base")
    assert (doc.in_flight, doc.last_base) == (3, "base")
    assert doc.entries[0].phase == phase.value
    assert from_doc(doc) == (entries, builds)


def test_unknown_phase():
    with pytest.raises(ValueError):
        from_doc(QueueDoc(entries=[EntryRow(branch="topic", head="head", phase="unknown")]))


def test_empty_doc():
    assert from_doc(QueueDoc()) == ([], {})
    assert to_doc([], {}, in_flight=1, last_base="") == QueueDoc()
