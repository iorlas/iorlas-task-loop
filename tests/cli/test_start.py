"""The `tl` console script: the pre-scan, the one resolver, its refusals and the one exec, with a recording exec port (no
process is replaced or started); and the exec loop end to end, in process (tl-8bh9.8.3 sections 5 and 16)."""

import json
import runpy
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import pytest
from install_doubles import A, B, Refusing, make_install, make_pin

from taskloop import start
from taskloop.installs import MANIFEST, LocalFiles, installs_root, python_of
from taskloop.start import Exec, PinRefused, Scan, resolve, run, scan

FILES = LocalFiles()
LAUNCHER = "/home/u/runner/.venv/bin/python"


class Replaced(Exception):
    """The recording exec port's stand-in for a replaced process image: control never comes back."""

    def __init__(self, path: str, argv: list[str]) -> None:
        super().__init__(path)
        self.path, self.argv = path, argv


def replace(path: str, argv: list[str]) -> NoReturn:
    raise Replaced(path, argv)


def unrunnable(path: str, argv: list[str]) -> NoReturn:
    raise PermissionError(13, "Permission denied", path)


@pytest.mark.parametrize(("args", "found"), [
    ([], Scan(None, None)),
    (["step", "list"], Scan(None, "step")),
    (["--config", "/m/a.toml", "step", "list"], Scan("/m/a.toml", "step")),
    (["--config=/m/a.toml", "version"], Scan("/m/a.toml", "version")),
    (["--config", "install", "step", "list"], Scan("install", "step")),
    (["--config", "--help", "step"], Scan("--help", "step")),
    (["-h"], Scan(None, None)),
    (["--help", "step"], Scan(None, None)),
    (["--config", "/m/a.toml", "--help"], Scan("/m/a.toml", None)),
    (["step", "--config", "/elsewhere.toml", "--help"], Scan(None, "step")),
    (["--config"], Scan(None, None)),
], ids=["empty", "command", "config", "config_equals", "config_named_install", "config_named_help", "help", "help_first", "config_help",
        "after_the_command_word_unread", "config_without_value"])
def test_the_pre_scan_reads_only_the_top_level_options_and_the_command_word(args: list[str], found: Scan) -> None:
    assert scan(args) == found


@pytest.mark.parametrize("args", [["install", "factory-v0.2.0"], ["pin", "--clear"], ["version", "--json"], [], ["-h"],
                                  ["--help", "step"], ["--config", "/m/config.toml"]])
@pytest.mark.parametrize("pin", ["none", "invalid", "missing"])
def test_exempt_commands_run_the_started_install_whatever_the_pin(tmp_path: Path, args: list[str], pin: str) -> None:
    if pin == "invalid":
        path = tmp_path / ".config/task-loop/config.pin.toml"
        path.parent.mkdir(parents=True)
        path.write_text("format = 2\n")
    if pin == "missing":
        make_pin(tmp_path, A)
    assert resolve(args, tmp_path, LAUNCHER, FILES) == Exec(LAUNCHER, tuple(args))


def test_no_pin_runs_the_started_install(tmp_path: Path) -> None:
    make_install(tmp_path, A)
    assert resolve(["step", "list"], tmp_path, LAUNCHER, FILES) == Exec(LAUNCHER, ("step", "list"))


def test_a_complete_pin_runs_its_install_with_argv_unchanged(tmp_path: Path) -> None:
    install = make_install(tmp_path, A, "factory-v0.2.0")
    make_pin(tmp_path, A, "factory-v0.2.0")
    args = ["step", "list", "--json", "--backlog", "tl"]
    decided = resolve(args, tmp_path, LAUNCHER, FILES)
    assert decided == Exec(str(python_of(install)), tuple(args))
    assert isinstance(decided, Exec)
    assert decided.argv() == [str(python_of(install)), "-I", "-m", "taskloop", *args]


def write_pin(home: Path, text: str) -> None:
    path = home / ".config/task-loop/config.pin.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text)


@pytest.mark.parametrize(("text", "detail"), [
    ("format = 1\ncommit = ", "not TOML"),
    (f'format = 1\ncommit = "{A}"\npinned_at = "t"\nwhy = "x"\n', "unknown key why"),
    (f'format = 2\ncommit = "{A}"\npinned_at = "t"\n', "format is 2"),
    (f'format = 1\ncommit = "{A[:12]}"\npinned_at = "t"\n', "not a full commit id"),
], ids=["toml", "unknown_key", "format_2", "short_id"])
def test_an_invalid_pin_refuses(tmp_path: Path, text: str, detail: str) -> None:
    write_pin(tmp_path, text)
    decided = resolve(["step", "list"], tmp_path, LAUNCHER, FILES)
    assert isinstance(decided, PinRefused) and decided.word == "pin:invalid" and decided.commit is None
    assert detail in decided.message and str(tmp_path / ".config/task-loop/config.pin.toml") in decided.message


def test_an_unreadable_pin_refuses_invalid(tmp_path: Path) -> None:
    path = make_pin(tmp_path, A)
    decided = resolve(["step", "list"], tmp_path, LAUNCHER, Refusing(unreadable=path))
    assert isinstance(decided, PinRefused) and decided.word == "pin:invalid" and "unreadable" in decided.message


def test_a_pin_without_its_install_refuses_missing_naming_the_fix(tmp_path: Path) -> None:
    make_install(tmp_path, B)  # another install is never guessed
    make_pin(tmp_path, A, "factory-v0.2.0")
    assert resolve(["step", "list"], tmp_path, LAUNCHER, FILES) == PinRefused(
        "pin:missing", A, f"pinned 3f2a9c4e1b07 (factory-v0.2.0) is not installed under {installs_root(tmp_path)}; "
        "tl install factory-v0.2.0 --checkout PATH, or tl pin --clear")


def test_a_pin_of_an_install_without_manifest_refuses_incomplete(tmp_path: Path) -> None:
    (make_install(tmp_path, A) / MANIFEST).unlink()
    (installs_root(tmp_path) / f"{A}.lock").write_text("")  # a held or free lock decides nothing here
    make_pin(tmp_path, A)
    decided = resolve(["step", "next"], tmp_path, LAUNCHER, FILES)
    assert isinstance(decided, PinRefused) and decided.word == "pin:incomplete" and str(installs_root(tmp_path) / A) in decided.message


@pytest.mark.parametrize("damage", ["other_commit", "python_absent", "not_executable", "dangling_link"])
def test_a_pin_of_a_broken_install_refuses_broken(tmp_path: Path, damage: str) -> None:
    install = make_install(tmp_path, A)
    python = python_of(install)
    if damage == "other_commit":
        (install / MANIFEST).write_text((install / MANIFEST).read_text().replace(A, B))
    else:
        python.unlink()
    if damage == "not_executable":
        python.write_text("")
    if damage == "dangling_link":
        python.symlink_to(tmp_path / "gone")
    make_pin(tmp_path, A)
    decided = resolve(["step", "list"], tmp_path, LAUNCHER, FILES)
    assert isinstance(decided, PinRefused) and decided.word == "pin:broken" and decided.commit == A


@pytest.mark.parametrize("separate", [True, False], ids=["separate", "equals"])
def test_two_configs_in_one_folder_read_their_own_pins(tmp_path: Path, separate: bool) -> None:
    folder = tmp_path / "m"
    a_install, b_install = make_install(tmp_path, A), make_install(tmp_path, B)
    make_pin(tmp_path, A, config=str(folder / "a.toml"))
    make_pin(tmp_path, B, config=str(folder / "b.toml"))

    def args(name: str) -> list[str]:
        return [*(["--config", str(folder / name)] if separate else [f"--config={folder / name}"]), "step", "list"]

    assert sorted(path.name for path in folder.iterdir()) == ["a.pin.toml", "b.pin.toml"]
    assert resolve(args("a.toml"), tmp_path, LAUNCHER, FILES) == Exec(str(python_of(a_install)), tuple(args("a.toml")))
    assert resolve(args("b.toml"), tmp_path, LAUNCHER, FILES) == Exec(str(python_of(b_install)), tuple(args("b.toml")))
    assert resolve(args("c.toml"), tmp_path, LAUNCHER, FILES) == Exec(LAUNCHER, tuple(args("c.toml")))  # no c.pin.toml
    assert resolve(["step", "list"], tmp_path, LAUNCHER, FILES) == Exec(LAUNCHER, ("step", "list"))  # nor a default pin


def test_a_config_named_install_is_a_config_and_the_command_is_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "install.pin.toml").write_text("format = 2\n")
    decided = resolve(["--config", "install", "step", "list"], tmp_path, LAUNCHER, FILES)
    assert isinstance(decided, PinRefused) and decided.word == "pin:invalid"


@pytest.mark.parametrize("config", [["--config", "/"], ["--config="], ["--config", ""]], ids=["root", "equals_empty", "empty"])
def test_a_config_path_without_a_name_refuses_invalid(tmp_path: Path, config: list[str]) -> None:
    decided = resolve([*config, "step", "list"], tmp_path, LAUNCHER, FILES)
    assert isinstance(decided, PinRefused) and decided.word == "pin:invalid" and "names no file" in decided.message
    assert resolve([*config, "version"], tmp_path, LAUNCHER, FILES) == Exec(LAUNCHER, (*config, "version"))  # exempt


def test_a_pinned_tag_that_is_no_tag_name_refuses_invalid(tmp_path: Path) -> None:
    make_install(tmp_path, A)
    write_pin(tmp_path, f'format = 1\ncommit = "{A}"\ntag = "x\\u001b[2J"\npinned_at = "t"\n')
    decided = resolve(["step", "list"], tmp_path, LAUNCHER, FILES)
    assert isinstance(decided, PinRefused) and decided.word == "pin:invalid" and "is not a tag name" in decided.message


def test_a_subcommands_own_flag_after_the_command_word_is_not_read(tmp_path: Path) -> None:
    make_install(tmp_path, A)
    make_pin(tmp_path, A)
    make_pin(tmp_path, B, config=str(tmp_path / "other.toml"))  # B is not installed: reading it would refuse
    decided = resolve(["step", "list", "--config", str(tmp_path / "other.toml")], tmp_path, LAUNCHER, FILES)
    assert isinstance(decided, Exec) and decided.python == str(python_of(installs_root(tmp_path) / A))


def run_tl(home: Path, args: Sequence[str]) -> Replaced:
    with pytest.raises(Replaced) as replaced:
        run(["/home/u/.local/bin/tl", *args], home, LAUNCHER, FILES, replace)
    return replaced.value


def test_start_replaces_itself_with_the_pinned_or_the_started_interpreter(tmp_path: Path) -> None:
    assert run_tl(tmp_path, ["version"]).argv == [LAUNCHER, "-I", "-m", "taskloop", "version"]
    install = make_install(tmp_path, A)
    make_pin(tmp_path, A)
    pinned = run_tl(tmp_path, ["step", "list", "--json"])
    python = str(python_of(install))
    assert (pinned.path, pinned.argv) == (python, [python, "-I", "-m", "taskloop", "step", "list", "--json"])


def test_a_refusal_prints_one_line_execs_nothing_and_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_pin(tmp_path, A, "factory-v0.2.0")
    assert run(["tl", "step", "list"], tmp_path, LAUNCHER, FILES, replace) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (f"tl: refused pin:missing: pinned 3f2a9c4e1b07 (factory-v0.2.0) is not installed under "
                          f"{installs_root(tmp_path)}; tl install factory-v0.2.0 --checkout PATH, or tl pin --clear\n")


def test_a_json_refusal_is_the_error_shape_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_pin(tmp_path, A)
    assert run(["tl", "step", "show", "tl-1", "--json"], tmp_path, LAUNCHER, FILES, replace) == 1
    output = capsys.readouterr()
    error = json.loads(output.err)["error"]
    assert output.out == "" and set(error) == {"kind", "commit", "message"}
    assert (error["kind"], error["commit"]) == ("pin:missing", A) and "tl install " + A in error["message"]


@pytest.mark.parametrize(("args", "expected"), [
    (["step", "list"], "tl: unavailable pin:exec: cannot run"),
    (["step", "list", "--json"], '{"error": {"kind": "pin:exec", "commit": null, "message": "cannot run'),
])
def test_a_failed_exec_is_unavailable_exit_3(tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], expected: str) -> None:
    make_install(tmp_path, A)
    make_pin(tmp_path, A)
    assert run(["tl", *args], tmp_path, LAUNCHER, FILES, unrunnable) == 3
    assert capsys.readouterr().err.startswith(expected)


def test_the_exec_lands_in_the_module_entry_which_never_resolves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    """A launcher and a pinned install: start execs `<pinned python> -I -m taskloop ...`; the target, `__main__` run in
    process with that argv, completes the command without resolving (a resolver that fails if called). The import
    contract `main-depends-on-cli` keeps `__main__` from importing `start`."""
    config = tmp_path / "m" / "config.toml"
    config.parent.mkdir()
    config.write_text("")
    install = make_install(tmp_path, A, "factory-v0.2.0")
    make_pin(tmp_path, A, "factory-v0.2.0", config=str(config))
    replaced = run_tl(tmp_path, ["--config", str(config), "config", "show", "--json"])
    assert replaced.argv[:4] == [str(python_of(install)), "-I", "-m", "taskloop"]

    def fail(*_args: object) -> NoReturn:
        raise AssertionError("the exec's target resolved again")

    monkeypatch.setattr(start, "resolve", fail)
    monkeypatch.setattr(start, "run", fail)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["taskloop", *replaced.argv[4:]])
    with pytest.raises(SystemExit) as ended:
        runpy.run_module("taskloop", run_name="__main__")
    assert ended.value.code == 0
    assert json.loads(capsys.readouterr().out)["file"] == {"path": str(config), "exists": True}
