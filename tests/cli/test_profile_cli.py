"""`tl profile show`: the resolved profile as human lines and JSON, a refusal's fixed word with exit 1 and Git unavailable
with exit 3, over a port fake in place of the Git adapter (no Git is started)."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from taskloop.attempt_types import Checkouts
from taskloop.cli import main
from taskloop.profile import NoCommit, Unavailable

MAIN = {"setup": [["just", "install"]], "checks": [{"name": "check", "argv": ["just", "check"], "timeout": 1800},
        {"name": "test", "argv": ["just", "test", "-k", "a b"], "timeout": 60}], "required": ["check", "test"], "target": "main"}


@dataclass
class Files:
    checkout: Path
    commits: dict[str, bytes] | None

    def blob(self, commit: str, _path: str) -> bytes | NoCommit | Unavailable | None:
        if self.commits is None:
            return Unavailable("git down")
        return self.commits.get(commit, NoCommit())


def wired(monkeypatch: pytest.MonkeyPatch, commits: dict[str, bytes] | None) -> list[Path]:
    seen: list[Path] = []

    def files(checkout: Path, _repos: Checkouts) -> Files:
        seen.append(checkout)
        return Files(checkout, commits)

    monkeypatch.setattr("taskloop.cli.GitProfileFiles", files)
    return seen


def test_the_resolved_profile_in_lines_and_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen = wired(monkeypatch, {"HEAD": json.dumps(MAIN).encode(), "main": json.dumps(MAIN).encode()})
    assert main(["profile", "show", "--checkout", "/repo"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Profile: setup and checks at HEAD; required and target from main",
        "Setup: just install",
        "Check check: just check (timeout 1800 s)",
        "Check test: just test -k 'a b' (timeout 60 s)",
        "Required: check, test",
        "Target: main",
    ]
    assert seen == [Path("/repo")]
    assert main(["profile", "show", "--checkout", "/repo", "--at", "HEAD", "--target", "main", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"at": "HEAD", "target_ref": "main", **MAIN}


@pytest.mark.parametrize("structured", [False, True])
def test_a_refusal_is_exit_1_and_unavailable_exit_3(structured: bool, monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    wired(monkeypatch, {"HEAD": b'{"engine": {}}'})
    flags = ["--json"] if structured else []
    assert main(["profile", "show", *flags]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    if structured:
        assert json.loads(output.err) == {"error": {"kind": "unknown_key", "side": "commit", "key": "engine",
                                                    "message": "Unknown keys: engine"}}
    else:
        assert output.err == "tl profile show: refused unknown_key (commit, engine): Unknown keys: engine\n"
    wired(monkeypatch, None)
    assert main(["profile", "show", *flags]) == 3
    error = capsys.readouterr().err
    assert (json.loads(error) == {"error": {"kind": "unavailable", "message": "git down"}} if structured else
            error == "tl profile show: unavailable: git down\n")


def test_zero_checks_print_none_and_a_forged_line_cannot_appear(monkeypatch: pytest.MonkeyPatch,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    wired(monkeypatch, {"HEAD": b"{}", "main": b"{}"})
    assert main(["profile", "show"]) == 0
    assert capsys.readouterr().out.splitlines()[1:] == ["Setup: just install", "Checks: (none)", "Required: (none)", "Target: main"]
    wired(monkeypatch, {"HEAD": json.dumps({"setup": [["just", "x\nRequired: (none)"]]}).encode()})
    assert main(["profile", "show"]) == 1
    error = capsys.readouterr().err
    assert error.count("\n") == 1
    assert error.startswith("tl profile show: refused bad_value (commit, setup[0][1])")
    wired(monkeypatch, {"HEAD": b'{"setup": [["just", "\\ud800"]]}'})
    assert main(["profile", "show"]) == 1
    assert "refused bad_value" in capsys.readouterr().err
