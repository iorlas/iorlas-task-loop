"""Inspect scoped tasks using the owning tracker client's semantic fake."""

from pathlib import Path

import pytest
from beads_client import BdError, Bead, Dep
from beads_client.testing import FakeTaskReadClient

from taskloop.task import TaskBinding, TaskInspectionError, TaskReference, TaskScope
from taskloop.tracker import inspect_task


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
