"""`tl workflow show` reads the file from Git through a port fake (no Git is started)."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from taskloop.attempt_types import Checkouts
from taskloop.cli import main
from taskloop.inspection_guide import WORKFLOW
from taskloop.profile import NoCommit, Unavailable
from taskloop.workflow import Reason

AGENT = b"""
[step.plan.agent]
harness = "codex"
model = "gpt-x"
[[step.plan.prompt]]
text = "Read AGENTS.md first, then assess the task carefully before changing anything at all in the repository."
[[step.plan.prompt]]
use = "task"
[[step.plan.prompt]]
use = "input_context"
[[step.implement.prompt]]
use = "input_context"
[[step.feedback]]
text = "Failed"
"""


@dataclass
class Files:
    checkout: Path
    blobs: dict[tuple[str, str], bytes] | None

    def blob(self, commit: str, path: str) -> bytes | NoCommit | Unavailable | None:
        if self.blobs is None:
            return Unavailable("git down")
        return self.blobs.get((commit, path))


def wired(monkeypatch: pytest.MonkeyPatch, blobs: dict[tuple[str, str], bytes] | None) -> list[Path]:
    seen: list[Path] = []

    def files(checkout: Path, _repos: Checkouts) -> Files:
        seen.append(checkout)
        return Files(checkout, blobs)

    monkeypatch.setattr("taskloop.cli_workflow.GitProfileFiles", files)
    return seen


def test_show_prints_digest_commit_agents_and_sections(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen = wired(monkeypatch, {("abc", ".task-loop/workflows/mine.toml"): AGENT})
    assert main(["workflow", "show", "--checkout", "/repo", "--at", "abc", "--name", "mine"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert seen == [Path("/repo")] and lines[0] == "Workflow mine at abc" and lines[1].startswith("Digest: ") and len(lines[1]) == 8 + 64
    assert lines[2] == "Read at: abc"
    assert "  harness: codex" in lines and "  model: gpt-x" in lines and "  effort: machine config" in lines
    first = "Read AGENTS.md first, then assess the task carefully before changing anything at all in the repository."
    assert f'  prompt 1: text "{first[:60].rstrip()}"' in lines
    assert "  prompt 2: renderer task" in lines and "  prompt 3: renderer input_context" in lines
    assert lines[-2:] == ["Feedback sections: 1", '  feedback 1: text "Failed"']


def test_show_json_has_the_same_facts(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    wired(monkeypatch, {("HEAD", ".task-loop/workflows/default.toml"): AGENT})
    assert main(["workflow", "show", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "default" and data["at"] == data["sha"] == "HEAD" and len(data["digest"]) == 64
    assert data["steps"]["plan"]["agent"] == {"harness": "codex", "model": "gpt-x", "effort": None, "compaction_token_limit": None}
    assert data["steps"]["implement"]["prompt"] == [{"kind": "renderer", "name": "input_context"}]
    assert data["feedback_sections"] == 1
    assert data["feedback"] == [{"kind": "text", "start": "Failed"}]


@pytest.mark.parametrize("structured", [False, True])
def test_show_displays_the_attempt_budget_feedback_renderer(
    structured: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = AGENT + b'[[step.feedback]]\nuse = "attempt_budget"\n'
    wired(monkeypatch, {("HEAD", ".task-loop/workflows/default.toml"): data})
    assert main(["workflow", "show", *(["--json"] if structured else [])]) == 0
    output = capsys.readouterr().out
    if structured:
        assert json.loads(output)["feedback"][1] == {"kind": "renderer", "name": "attempt_budget"}
    else:
        assert "  feedback 2: renderer attempt_budget" in output.splitlines()


@pytest.mark.parametrize("structured", [False, True])
def test_a_missing_or_unusable_file_is_exit_1_and_unavailable_exit_3(
    structured: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    flags = ["--json"] if structured else []
    wired(monkeypatch, {})
    assert main(["workflow", "show", *flags]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    if structured:
        assert json.loads(output.err) == {
            "error": {
                "kind": "missing",
                "where": ".task-loop/workflows/default.toml",
                "message": "missing: .task-loop/workflows/default.toml",
            }
        }
    else:
        assert output.err.endswith(WORKFLOW["missing"] + "\n") and output.err.startswith("tl workflow show: missing: ")
    wired(monkeypatch, {("HEAD", ".task-loop/workflows/default.toml"): b"[step.plan"})
    assert main(["workflow", "show", *flags]) == 1
    assert ("not_toml" if structured else WORKFLOW["not_toml"]) in capsys.readouterr().err
    wired(monkeypatch, None)
    assert main(["workflow", "show", *flags]) == 3
    error = capsys.readouterr().err
    assert json.loads(error)["error"]["kind"] == "unavailable" if structured else error.endswith(WORKFLOW["unavailable"] + "\n")


def test_every_refusal_reason_has_a_guide() -> None:
    assert {str(reason) for reason in Reason} | {"unavailable"} == set(WORKFLOW)
