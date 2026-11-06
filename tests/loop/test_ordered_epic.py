"""An epic labelled `ordered`: a child that names nothing it follows is not taken (the order is data, not a markdown line)."""

from unittest import mock

import pytest

from taskloop.app.loop.queue import QueueRule
from taskloop.contracts.bead import BdError, Bead, Dep
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure


def bead(name: str, parent: str = "", labels: list[str] | None = None, deps: list[Dep] | None = None) -> Bead:
    return Bead(id=BeadId(name), title=name, status="open", parent=parent, labels=labels or [], dependencies=deps or [])


PARENT_LINK = Dep(id="t-1", type="parent-child")
BLOCKS = Dep(id="t-1.1", type="blocks")


def rule(shown: dict[str, Bead | None]) -> QueueRule:
    store = mock.Mock()
    store.show.side_effect = shown.get
    return QueueRule(store, EngineConfig(), {}, lambda _: "")


@pytest.mark.parametrize(("epic_labels", "deps", "skipped"), [
    (["ordered"], [PARENT_LINK], True),
    (["ordered"], [], True),
    (["ordered"], [PARENT_LINK, BLOCKS], False),  # it names what it follows
    ([], [PARENT_LINK], False),  # an unlabelled epic
])
def test_a_child_of_an_ordered_epic_needs_a_blocks_dep(epic_labels: list[str], deps: list[Dep], skipped: bool) -> None:
    child = bead("t-1.2", parent="t-1", deps=deps)
    r = rule({"t-1": bead("t-1", labels=epic_labels), "t-1.2": child})
    got = r.unordered(child)
    assert (got is not None) is skipped
    if got:
        assert got.kind == "unordered" and "ordered epic t-1" in got.why and "bd dep add" in got.why


def test_a_bead_with_no_parent_is_not_skipped() -> None:
    assert rule({}).unordered(bead("t-9")) is None


def test_a_bd_failure_on_the_epic_or_the_child_does_not_skip() -> None:
    down = BdFailure(BdError(kind="other", text="unavailable"))
    child = bead("t-1.2", parent="t-1")
    store = mock.Mock()
    store.show.side_effect = down
    assert QueueRule(store, EngineConfig(), {}, lambda _: "").unordered(child) is None
    store.show.side_effect = lambda i: bead("t-1", labels=["ordered"]) if i == "t-1" else (_ for _ in ()).throw(down)
    assert QueueRule(store, EngineConfig(), {}, lambda _: "").unordered(child) is None


def test_the_queue_lists_the_skip() -> None:
    child = bead("t-1.2", parent="t-1")
    r = rule({"t-1": bead("t-1", labels=["ordered"]), "t-1.2": child})
    q = r.rank([child], "")
    assert [(s.bead, s.skip.kind) for s in q.skipped] == [("t-1.2", "unordered")] and q.ranked == []
