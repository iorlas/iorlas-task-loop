"""Exercise the real parser and module entry without launching a process."""

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
    assert "steps built: plan, implement; publishes task/<id>; no merge or land" in " ".join(output.out.split())
    assert output.err == ""


@pytest.mark.parametrize(
    "arguments",
    [["step", "-h"], ["step", "start", "-h"], ["step", "show", "-h"], ["step", "list", "-h"], ["step", "verify", "-h"],
     ["step", "release", "-h"]],
)
def test_step_help_names_the_steps_built(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(arguments)
    assert result.value.code == 0
    assert "steps built: plan, implement; publishes task/<id>; no merge or land" in " ".join(capsys.readouterr().out.split())


def test_publish_help_says_it_pushes_as_you_never_forced(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["step", "publish", "-h"])
    assert result.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "Push the step's verified commit to origin's task/<id> as you, never forced; nothing merges or lands" in text


@pytest.mark.parametrize(
    "arguments",
    [["plan"], ["step"], ["implement"], ["--unknown"], ["--he"], ["land", "tl-123"], ["step", "prepare"], ["slot"], ["config"]],
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
