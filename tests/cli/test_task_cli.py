"""Show scoped tasks through the real CLI and the owning semantic read fake."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from beads_client import BdError, Bead, TaskReadClient
from beads_client.testing import FakeTaskReadClient

from taskloop import composition
from taskloop.cli import main
from taskloop.task import TaskReference, TaskScope


@pytest.mark.parametrize("structured", [False, True])
def test_task_show_preserves_requirements(
    structured: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeTaskReadClient(
        (Bead("t-1", title="One task", description="Raw requirements\n  stay raw.", acceptance_criteria="Acceptance"),)
    )

    def make_client(actor: str, *, cwd: str) -> TaskReadClient:
        assert actor == "taskloop"
        assert cwd == str(tmp_path)
        return client

    monkeypatch.setattr(composition, "Bd", make_client)
    assert (
        main(["task", "show", "t-1", "--backlog", "configured", "--tracker-root", str(tmp_path), *(["--json"] if structured else [])]) == 0
    )
    output = capsys.readouterr()
    assert output.err == ""
    if structured:
        assert json.loads(output.out) == {
            "reference": asdict(TaskReference(TaskScope("configured"), "t-1")),
            "title": "One task",
            "requirements": "Raw requirements\n  stay raw.",
            "acceptance": "Acceptance",
            "dependencies": [],
        }
    else:
        assert "Task: t-1" in output.out
        assert "Backlog: beads/configured" in output.out
        assert "One task" in output.out
        assert "Raw requirements\n  stay raw." in output.out
        assert "Acceptance" in output.out
    assert client.reads == ["t-1"]


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize(
    "failure, kind",
    [
        (None, "not_found"),
        (BdError("malformed", "wrong response"), "malformed"),
        (BdError("other", "tracker unavailable"), "tracker_unavailable"),
    ],
)
def test_task_failures_remain_distinct(
    failure: BdError | None,
    kind: str,
    structured: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeTaskReadClient(faults={"t-1": failure} if failure else {})

    def make_client(actor: str, *, cwd: str) -> TaskReadClient:
        return client

    monkeypatch.setattr(composition, "Bd", make_client)
    assert (
        main(["task", "show", "t-1", "--backlog", "configured", "--tracker-root", str(tmp_path), *(["--json"] if structured else [])]) == 1
    )
    output = capsys.readouterr()
    assert output.out == ""
    if structured:
        error = json.loads(output.err)["error"]
        assert error["kind"] == kind
        assert error["reference"] == asdict(TaskReference(TaskScope("configured"), "t-1"))
        if failure:
            assert error["backend_kind"] == failure.kind
            assert error["message"] == failure.text
    else:
        assert output.err.startswith("tl task show: ")
    assert client.reads == ["t-1"]


@pytest.mark.parametrize(
    "backlog, root", [("", "."), (" ", "."), ("configured", ""), ("configured", "~__taskloop_missing_home_6c6fd109__/tracker")]
)
def test_invalid_binding_never_constructs_or_reads_a_tracker(
    backlog: str, root: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden_client(actor: str, *, cwd: str) -> TaskReadClient:
        pytest.fail("an invalid binding must not access a tracker")

    monkeypatch.setattr(composition, "Bd", forbidden_client)
    assert main(["task", "show", "t-1", "--backlog", backlog, "--tracker-root", root, "--json"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["kind"] == "invalid_binding"


def test_missing_tracker_directory_is_an_invalid_binding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["task", "show", "t-1", "--backlog", "configured", "--tracker-root", str(tmp_path / "missing"), "--json"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["kind"] == "invalid_binding"


@pytest.mark.parametrize(
    "arguments",
    [
        ["task"],
        ["task", "show"],
        ["task", "show", "t-1"],
        ["task", "show", "t-1", "--backlog", "configured"],
        ["task", "show", "t-1", "--tracker-root", "."],
        ["task", "show", "t-1", "--backlog", "configured", "--tracker-root", ".", "--js"],
    ],
)
def test_task_show_requires_explicit_inputs(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as failure:
        main(arguments)
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "error:" in output.err
