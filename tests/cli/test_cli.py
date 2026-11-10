"""Exercise the real parser and module entry without launching a process."""

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
    assert "attempt only: no task branch, publication or release" in " ".join(output.out.split())
    assert output.err == ""


@pytest.mark.parametrize("arguments", [["plan", "-h"], ["plan", "start", "-h"], ["plan", "show", "-h"], ["plan", "verify", "-h"]])
def test_plan_help_says_attempt_only(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(arguments)
    assert result.value.code == 0
    assert "attempt only: no task branch, publication or release" in " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize(
    "arguments", [["plan"], ["implement"], ["--unknown"], ["--he"], ["land", "tl-123"], ["plan", "prepare"], ["slot"], ["config"]]
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
