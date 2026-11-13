"""The documented checkout forms use the current directory only for profile inspection."""

import json
from pathlib import Path

import pytest

from taskloop.attempt_types import Checkouts
from taskloop.cli import main


class ProfileFiles:
    def blob(self, _commit: str, _path: str) -> bytes:
        return b"{}"


@pytest.mark.parametrize("structured", [False, True])
def test_profile_checkout_defaults_to_the_current_directory(
    structured: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[Path] = []

    def files(checkout: Path, _repos: Checkouts) -> ProfileFiles:
        seen.append(checkout)
        return ProfileFiles()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("taskloop.cli.GitProfileFiles", files)
    assert main(["profile", "show", *(["--json"] if structured else [])]) == 0
    assert seen == [tmp_path]
    output = capsys.readouterr()
    assert output.err == ""
    if structured:
        assert json.loads(output.out)["target"] == "main"
    else:
        assert output.out.startswith("Profile: setup and checks at HEAD; required and target from main\n")


@pytest.mark.parametrize(("argv", "required"), [
    (["repo", "inspect"], "PATH"),
    (["slot", "adopt"], "CHECKOUT"),
    (["step", "start", "tl-1", "--backlog", "tasks", "--tracker-root", "/tracker", "--model", "m", "--effort", "high",
      "--minutes", "30"], "--checkout"),
])
def test_positional_checkouts_and_start_checkout_are_required_before_an_operation(
    argv: list[str], required: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("taskloop.cli.inspect_repo", lambda _arguments: pytest.fail("inspection started"))
    monkeypatch.setattr("taskloop.cli.cli_step.run", lambda _arguments: pytest.fail("operation started"))
    with pytest.raises(SystemExit) as ended:
        main(argv)
    assert ended.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert f"the following arguments are required: {required}" in output.err
