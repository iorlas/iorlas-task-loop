"""Every command explains itself in its own --help, and the flags that bind a command to a tracker and repository say what they are."""

import pytest

from taskloop.cli import main

COMMANDS = [
    ["repo", "show"], ["task", "show"], ["profile", "show"], ["drain"], ["version"], ["config", "show"], ["slot", "adopt"],
    ["step", "start"], ["step", "show"], ["step", "list"], ["step", "setup-times"], ["step", "commit"], ["step", "release"],
    ["rounds", "once"], ["rounds", "start"], ["step", "publish"], ["step", "land"],
]


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_a_command_help_has_a_description_before_its_options(command: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main([*command, "--help"])
    paragraphs = capsys.readouterr().out.split("\n\n")
    assert len(paragraphs) > 2 and not paragraphs[1].startswith(("positional arguments", "options"))


@pytest.mark.parametrize("command", [["step", "start"], ["rounds", "once"], ["rounds", "start"]], ids=" ".join)
def test_the_binding_flags_have_help(command: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main([*command, "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "The tracker backlog" in text and "The directory of the task tracker" in text and "Your checkout of the repository" in text
