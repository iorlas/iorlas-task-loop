"""The tracker's reads for a read-only view (`tracker.task_facts`, `task_comments`, `task_titles`, `ready_titles`) over
beads_client's in-memory read client: the mapping, the comment order, unknown ids, and failures never read as empty."""

from collections.abc import Callable

import pytest
from beads_client import BdError, Bead, Comment, Dep
from beads_client.testing import FakeTaskReadClient

from taskloop.task import ReadyTitle, TaskComment, TaskFacts, TaskInspectionError
from taskloop.tracker import ready_titles, task_comments, task_facts, task_titles

DOWN = BdError("timeout", "bd did not answer")


class Commented:
    def __init__(self, rows: list[Comment], fault: BdError | None = None) -> None:
        self.rows, self.fault = rows, fault

    def comments(self, bead: str) -> list[Comment]:
        if self.fault:
            raise self.fault
        return self.rows


def test_facts_map_every_field_and_default_the_absent_ones() -> None:
    full = Bead(
        "t-1", "Widget", "open", priority=1, assignee="ann", labels=("auto", "ui"), description="why", design="how",
        acceptance_criteria="done when", notes="n", dependencies=(Dep("t-0", "blocks"), Dep("t-p", "parent-child")),
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-02T00:00:00Z",
    )
    client = FakeTaskReadClient((full, Bead("t-2")))
    assert task_facts(client, "t-1") == TaskFacts(
        "t-1", "Widget", "open", 1, ("auto", "ui"), "ann", "why", "how", "done when", "n", ("t-0", "t-p"),
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
    )
    assert task_facts(client, "t-2") == TaskFacts("t-2", "", "", None, (), None, "", "", "", "", (), "", "")
    assert task_facts(client, "t-9") is None


def test_comments_keep_the_trackers_order() -> None:
    rows = [Comment("ann", "first", "2026-01-01"), Comment("bob", "second")]
    assert task_comments(Commented(rows), "t-1") == (TaskComment("ann", "2026-01-01", "first"), TaskComment("bob", "", "second"))


def test_titles_skip_unknown_ids_and_read_each_id_once() -> None:
    client = FakeTaskReadClient((Bead("t-1", "One"), Bead("t-2", "Two")))
    assert task_titles(client, ["t-2", "t-9", "t-1", "t-2"]) == {"t-2": "Two", "t-1": "One"}
    assert client.reads == ["t-2", "t-9", "t-1"]


def test_ready_listing_is_the_trackers_order_for_the_label() -> None:
    records = (Bead("t-3", "C", priority=2, labels=("auto",), created_at="c"), Bead("t-1", "A", labels=("auto",)), Bead("t-2", "B"))
    client = FakeTaskReadClient(records, ready=["t-3", "t-1", "t-2"])
    assert ready_titles(client, "auto") == (ReadyTitle("t-3", "C", 2, "c"), ReadyTitle("t-1", "A", None, ""))


@pytest.mark.parametrize("read", [
    lambda: task_facts(FakeTaskReadClient(faults={"t-1": DOWN}), "t-1"),
    lambda: task_titles(FakeTaskReadClient(faults={"t-1": DOWN}), ["t-1"]),
    lambda: task_comments(Commented([], DOWN), "t-1"),
    lambda: ready_titles(FakeTaskReadClient(ready_fault=DOWN), "auto"),
], ids=["facts", "titles", "comments", "ready"])
def test_a_failed_read_raises_and_is_never_empty(read: Callable[[], object]) -> None:
    with pytest.raises(TaskInspectionError) as raised:
        read()
    assert raised.value.kind == "tracker_unavailable"
