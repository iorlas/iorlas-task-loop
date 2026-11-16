"""Exercise the real parser and module entry without launching a process."""

import importlib.metadata
import json
import os
import runpy

import pytest

from taskloop.cli import main


@pytest.mark.parametrize("arguments", [[], ["-h"], ["--help"]])
def test_help(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    if arguments:
        with pytest.raises(SystemExit) as result:
            main(arguments)
        assert result.value.code == 0
    else:
        assert main(arguments) == 0
    output = capsys.readouterr()
    assert "usage: tl" in output.out
    assert BUILT in " ".join(output.out.split())
    assert output.err == ""


BUILT = ("Steps built: plan, implement and check. Committed results are published on the task branch. "
         "The profile selects automatic land during a round or manual land by the owner.")


def test_step_help_names_the_steps_built_once_and_each_command_help_does_not_repeat_it(capsys: pytest.CaptureFixture[str]) -> None:
    for arguments in (["step", "-h"], ["step", "start", "-h"], ["step", "show", "-h"], ["step", "list", "-h"],
                      ["step", "commit", "-h"], ["step", "release", "-h"]):
        with pytest.raises(SystemExit) as result:
            main(arguments)
        assert result.value.code == 0
        assert (BUILT in " ".join(capsys.readouterr().out.split())) == (arguments == ["step", "-h"])


def test_publish_help_says_it_pushes_as_you_never_forced(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["step", "publish", "-h"])
    assert result.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert ("Push the step's commit accepted by factory commit to origin's task/<id> as you, "
            "never forced; nothing merges or lands") in text


def test_commit_help_describes_judgment_release_and_publication(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["step", "commit", "-h"])
    assert result.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert ("Complete factory commit: obtain the result commit and judge the step's rules, "
            "then release a clean slot and publish an accepted result") in text
    assert "verify" not in text and "verification" not in text


def test_legacy_step_command_is_not_an_alias(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["step", "verify"])
    assert result.value.code == 2
    assert "invalid choice: 'verify'" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [["plan"], ["step"], ["implement"], ["--unknown"], ["--he"], ["land", "tl-123"], ["step", "prepare"], ["slot"], ["config"],
     ["install"], ["pin"], ["report"], ["repo", "register"], ["task", "create"],
     ["slot", "list"], ["slot", "release"], ["slot", "hold"]],
)
def test_invalid_request(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(arguments)
    assert result.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "usage: tl" in output.err
    assert "error:" in output.err


@pytest.mark.parametrize("arguments, code", [(["--help"], 0), (["plan"], 2)])
def test_module_entry(arguments: list[str], code: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["taskloop", *arguments])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("taskloop", run_name="__main__")
    assert result.value.code == code
    output = capsys.readouterr()
    assert "usage: tl" in (output.out if code == 0 else output.err)


def test_bd_location_overrides_are_dropped_before_any_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("BEADS_DIR", "/elsewhere/.beads")
    assert main([]) == 0
    capsys.readouterr()
    assert "BEADS_DIR" not in os.environ  # a claim, its unclaim and the entry it launches use the given tracker root


def test_version_prints_the_running_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    expected = importlib.metadata.version("iorlas-task-loop")
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == expected
    assert main(["version", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"version": expected}
