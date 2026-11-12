"""Inspect scoped tasks using the owning tracker client's semantic fake."""

from pathlib import Path

import pytest
from beads_client import BdError, Bead, Dep
from beads_client.testing import FakeTaskReadClient
from doubles import ReadyTracker

from taskloop.task import TaskBinding, TaskInspectionError, TaskReference, TaskScope
from taskloop.tracker import TaskRow, ancestry, inspect_task, ready_rows


def test_equal_task_ids_keep_their_explicit_backlog_and_requirements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    record = Bead("t-1", title="First", description="  Raw requirements\n\nKeep *meaning*.\n", acceptance_criteria="  Acceptance\n")
    first = FakeTaskReadClient((record,))
    second = FakeTaskReadClient((Bead("t-1", description="Other requirements"),))
    one = inspect_task(TaskBinding(TaskScope("first"), tmp_path), first, "t-1")
    two = inspect_task(TaskBinding(TaskScope("second"), tmp_path), second, "t-1")
    assert one.reference != two.reference
    assert one.reference == TaskReference(TaskScope("first"), "t-1")
    assert one.title == "First"
    assert one.requirements == record.description
    assert one.acceptance == record.acceptance_criteria
    assert two.requirements == "Other requirements"
    assert first.reads == second.reads == ["t-1"]


def test_the_tracker_status_and_assignee_are_mapped(tmp_path: Path) -> None:
    client = FakeTaskReadClient((Bead("t-1", status="in_progress", assignee="taskloop"),))
    result = inspect_task(TaskBinding(TaskScope("configured"), tmp_path), client, "t-1")
    assert (result.status, result.assignee) == ("in_progress", "taskloop")


def test_dependency_relationships_keep_scoped_targets(tmp_path: Path) -> None:
    client = FakeTaskReadClient((Bead("t-1", dependencies=(Dep("t-0", "blocks", "Earlier", "closed"), Dep("t-parent", "parent-child"))),))
    scope = TaskScope("configured")
    result = inspect_task(TaskBinding(scope, tmp_path), client, "t-1")
    assert [(d.reference, d.relationship, d.title, d.status) for d in result.dependencies] == [
        (TaskReference(scope, "t-0"), "blocks", "Earlier", "closed"),
        (TaskReference(scope, "t-parent"), "parent-child", "", ""),
    ]
    assert client.reads == ["t-1"]


def test_empty_requirements_are_successful_inspection(tmp_path: Path) -> None:
    client = FakeTaskReadClient((Bead("t-1"),))
    result = inspect_task(TaskBinding(TaskScope("configured"), tmp_path), client, "t-1")
    assert (result.title, result.requirements, result.acceptance, result.dependencies) == ("", "", "", ())
    assert client.reads == ["t-1"]


@pytest.mark.parametrize(
    "backend_kind, kind",
    [
        ("malformed", "malformed"),
        ("timeout", "tracker_unavailable"),
        ("missing_binary", "tracker_unavailable"),
        ("other", "tracker_unavailable"),
    ],
)
def test_tracker_read_failures_are_not_missing(tmp_path: Path, backend_kind: str, kind: str) -> None:
    faults = {
        "malformed": BdError("malformed", "wrong response"),
        "timeout": BdError("timeout", "no answer"),
        "missing_binary": BdError("missing_binary", "tracker missing"),
        "other": BdError("other", "database unavailable"),
    }
    client = FakeTaskReadClient(faults={"t-1": faults[backend_kind]})
    with pytest.raises(TaskInspectionError) as failure:
        inspect_task(TaskBinding(TaskScope("configured"), tmp_path), client, "t-1")
    assert failure.value.kind == kind
    assert failure.value.backend_kind == backend_kind
    assert faults[backend_kind].text in str(failure.value)
    assert failure.value.reference == TaskReference(TaskScope("configured"), "t-1")
    assert client.reads == ["t-1"]


def test_authoritative_absence_preserves_the_requested_reference(tmp_path: Path) -> None:
    client = FakeTaskReadClient()
    with pytest.raises(TaskInspectionError) as failure:
        inspect_task(TaskBinding(TaskScope("configured"), tmp_path), client, "missing")
    assert failure.value.kind == "not_found"
    assert failure.value.reference == TaskReference(TaskScope("configured"), "missing")
    assert client.reads == ["missing"]


@pytest.mark.parametrize("backlog", ["", "  "])
def test_empty_backlog_is_refused(backlog: str) -> None:
    with pytest.raises(TaskInspectionError, match="backlog") as failure:
        TaskScope(backlog)
    assert failure.value.kind == "invalid_binding"


NOW = 1_800_000_000.0  # 2027-01-15T08:00:00Z


def test_a_discarded_factory_leaves_in_progress_rows_with_an_expired_lease_that_a_round_takes_again() -> None:
    def claimed(task_id: str, lease: str = "", assignee: str = "taskloop") -> Bead:
        return Bead(task_id, status="in_progress", assignee=assignee, labels=("auto",), lease_expires_at=lease)

    records = [
        claimed("t-old", "2027-01-15T07:00:00Z"), claimed("t-live", "2027-01-15T09:00:00Z"), claimed("t-nolease"),
        claimed("t-other", "2027-01-15T07:00:00Z", "someone"), Bead("t-open", status="open", labels=("auto",)),
    ]
    rows = ready_rows(ReadyTracker(records, ready=["t-open"]), "auto", NOW, retake=True)
    assert [row.task_id for row in rows] == ["t-open", "t-old"]
    assert [row.task_id for row in ready_rows(ReadyTracker(records, ready=["t-open"]), "auto", NOW)] == ["t-open"]  # not by default


def test_ready_rows_keep_the_trackers_order_label_and_scheduling_fields() -> None:
    records = [
        Bead("t-3", priority=None, parent="p-1", assignee="taskloop", labels=("auto",)),
        Bead("t-1", priority=0, labels=("auto",)),
        Bead("t-2", priority=1, labels=("other",)),
    ]
    client = ReadyTracker(records, ready=["t-3", "t-1", "t-2"])
    assert ready_rows(client, "auto", NOW) == (TaskRow("t-3", None, "p-1", "taskloop"), TaskRow("t-1", 0, "", ""))
    assert client.ready_reads == ["auto"] and client.reads == []


@pytest.mark.parametrize("fault, kind", [
    (BdError("malformed", "bd failed"), "malformed"), (BdError("timeout", "bd failed"), "tracker_unavailable"),
    (BdError("other", "bd failed"), "tracker_unavailable"),
])
def test_a_failed_ready_read_raises_and_is_never_empty(fault: BdError, kind: str) -> None:
    client = ReadyTracker(ready_fault=fault)
    with pytest.raises(TaskInspectionError) as failure:
        ready_rows(client, "auto", NOW)
    assert (failure.value.kind, failure.value.backend_kind) == (kind, fault.kind) and "bd failed" in str(failure.value)


def test_ancestry_reads_each_unique_missing_parent_once_failures_included() -> None:
    client = ReadyTracker([Bead("p-1", priority=0, parent="p-2"), Bead("p-2")], faults={"p-9": BdError("timeout", "slow")})
    lookup = ancestry(client, (TaskRow("t-1", 1, "p-1", ""),))
    assert lookup("t-1") == TaskRow("t-1", 1, "p-1", "")  # a ready row: no read
    assert lookup("p-1") == lookup("p-1") == TaskRow("p-1", 0, "p-2", "")
    assert lookup("absent") is None and lookup("absent") is None
    for _ in range(2):
        with pytest.raises(TaskInspectionError) as failure:
            lookup("p-9")
        assert failure.value.kind == "tracker_unavailable"
    assert client.reads == ["p-1", "absent", "p-9"]


def test_a_task_deleted_from_the_tracker_is_not_found_not_unavailable(tmp_path: Path) -> None:
    """bd answers a deleted bead with an error, not an empty read: it must not read as an unreachable tracker (which stops
    every round)."""
    gone = BdError("other", 'resolving t-1: no issue found matching "t-1"')
    with pytest.raises(TaskInspectionError) as failure:
        inspect_task(TaskBinding(TaskScope("configured"), tmp_path), FakeTaskReadClient(faults={"t-1": gone}), "t-1")
    assert failure.value.kind == "not_found"
