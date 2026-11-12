"""`tl pin REV` and `tl pin --clear`: REV resolved only from installed manifests, the one validity rule (`installs.state`),
the atomic pin write, the drain procedure, and never factory.db (tl-8bh9.8.3 sections 6.2, 7, 8 and 11)."""

import sqlite3
from pathlib import Path

import pytest
from install_doubles import NOW, A, B, Refusing, make_install, make_pin

from taskloop import pin_op, start
from taskloop.cli import main
from taskloop.cli_install import EFFECT
from taskloop.installs import MANIFEST, LocalFiles, installs_root, python_of
from taskloop.pin_file import Pin, read

FILES = LocalFiles()
C = "5d0c3e8f1a22" + "c" * 28


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh home under tmp_path; no factory.db may be opened by any `tl pin` call."""
    monkeypatch.setenv("HOME", str(tmp_path))

    def refuse(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        raise AssertionError("tl pin opened a database")

    monkeypatch.setattr(sqlite3, "connect", refuse)
    return tmp_path


def default_pin(home: Path) -> Path:
    return home / ".config/task-loop/config.pin.toml"


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[str], str]:
    code = main(list(argv))
    output = capsys.readouterr()
    return code, output.out.splitlines(), output.err


def test_pinning_a_commit_writes_the_pin_beside_the_default_config_and_prints_the_drain(
        home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_install(home, A, "factory-v0.2.0")
    code, out, err = run(capsys, "pin", A)
    path = default_pin(home)  # the config folder did not exist: it is made
    assert (code, err) == (0, "")
    assert out == [f"Pinned: 3f2a9c4e1b07 (factory-v0.2.0), in {path}", "Was: none",
                   f"{EFFECT} If rounds or attempts still run: tl pin --clear back, drain, then make this change again."]
    found = read(FILES, path)
    assert isinstance(found, Pin) and (found.commit, found.tag) == (A, "factory-v0.2.0")


def test_pinning_a_tag_finds_its_install_among_the_manifests_and_names_the_pin_it_replaced(
        home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_install(home, A, "factory-v0.2.0")
    make_install(home, B, "factory-v0.1.0")
    (installs_root(home) / C).mkdir()  # an install still building: no manifest, never read as a tag
    (installs_root(home) / f"{A}.lock").write_text("held")
    (installs_root(home) / "factory-v0.2.0").mkdir()  # not named by a commit id: not an install
    make_pin(home, B, "factory-v0.1.0")
    code, out, _err = run(capsys, "pin", "factory-v0.2.0")
    assert code == 0 and out == [f"Pinned: 3f2a9c4e1b07 (factory-v0.2.0), in {default_pin(home)}",
                                  "Was: 9b1e07d2aa31 (factory-v0.1.0)",
                                  f"{EFFECT} If rounds or attempts still run: tl pin factory-v0.1.0 back, drain, then make this "
                                  "change again."]
    assert start.resolve(["step", "list"], home, "/launcher/python", FILES) == start.Exec(
        str(python_of(installs_root(home) / A)), ("step", "list"))  # the next start runs it


def test_pinning_the_pinned_commit_is_already_and_leaves_the_file_unchanged(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_install(home, A, "factory-v0.2.0")
    path = make_pin(home, A, "factory-v0.2.0")
    before = path.read_bytes()
    code, out, _err = run(capsys, "pin", "factory-v0.2.0")
    assert (code, out) == (0, [f"Pinned: already 3f2a9c4e1b07 (factory-v0.2.0), in {path}"])
    assert path.read_bytes() == before


def test_an_untagged_install_is_pinned_by_commit_with_no_tag(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_install(home, A)
    code, out, _err = run(capsys, "pin", A)
    assert code == 0 and out[0] == f"Pinned: 3f2a9c4e1b07, in {default_pin(home)}"
    assert read(FILES, default_pin(home)) == Pin(A, None, read_pinned_at(home))


def read_pinned_at(home: Path) -> str:
    found = read(FILES, default_pin(home))
    assert isinstance(found, Pin)
    return found.pinned_at


def damage(home: Path, how: str) -> None:
    if how == "incomplete":
        (installs_root(home) / A).mkdir(parents=True)
    elif how == "broken":
        make_install(home, A, manifest="format = 2\n")
    elif how == "python":
        python_of(make_install(home, A)).unlink()


@pytest.mark.parametrize(("how", "rev", "word"), [
    ("absent", A, "not_installed"), ("absent", "factory-v0.2.0", "not_installed"), ("incomplete", A, "incomplete"),
    ("broken", A, "broken"), ("python", A, "broken"), ("absent", A[:12], "not_installed"), ("absent", "a..b", "revision"),
], ids=["commit_absent", "tag_absent", "incomplete", "broken_manifest", "python_missing", "short_id_is_no_tag_found", "revision"])
def test_a_rev_without_a_complete_install_is_refused_and_writes_nothing(
        home: Path, capsys: pytest.CaptureFixture[str], how: str, rev: str, word: str) -> None:
    damage(home, how)
    path = make_pin(home, B)
    before = path.read_bytes()
    code, out, err = run(capsys, "pin", rev)
    assert (code, out) == (1, []) and err.startswith(f"tl pin: refused {word}: ")
    assert path.read_bytes() == before and sorted(child.name for child in path.parent.iterdir()) == [path.name]


def test_an_incomplete_install_is_named_by_its_path(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    damage(home, "incomplete")
    _code, _out, err = run(capsys, "pin", A)
    assert err == (f"tl pin: refused incomplete: {installs_root(home) / A} has no manifest (an install never finished, or is "
                   "still building)\n")


def test_a_tag_recorded_by_two_installs_is_ambiguous(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_install(home, A, "factory-v0.2.0")
    make_install(home, B, "factory-v0.2.0")  # the tag was moved and installed again
    code, _out, err = run(capsys, "pin", "factory-v0.2.0")
    assert code == 1 and err == (f"tl pin: refused ambiguous: tag factory-v0.2.0 is recorded by 2 installs ({A}, {B}); "
                                 "tl pin COMMIT\n")
    assert not default_pin(home).exists()
    assert run(capsys, "pin", B)[0] == 0  # the commit decides


def test_the_pin_follows_the_config_in_use_and_reads_no_config_file(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_install(home, A)
    code, out, _err = run(capsys, "--config", str(home / "m5" / "config.toml"), "pin", A)
    assert code == 0 and out[0] == f"Pinned: 3f2a9c4e1b07, in {home / 'm5' / 'config.pin.toml'}"
    assert not default_pin(home).exists() and sorted(child.name for child in (home / "m5").iterdir()) == ["config.pin.toml"]


@pytest.mark.parametrize("argv", [["pin", A], ["pin", "--clear"]])
def test_a_config_without_a_name_is_refused_config(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    make_install(Path.home(), A)
    code, _out, err = run(capsys, "--config", "/", *argv)
    assert code == 1 and err == "tl pin: refused config: --config '/' names no file, so it has no pin file\n"


def test_the_config_and_its_factory_db_are_never_opened(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A config naming an absent factory.db; `sqlite3.connect` fails the test if called (the fixture)."""
    make_install(home, A)
    config = home / "m" / "config.toml"
    config.parent.mkdir()
    config.write_text(f'db = "{home / "state" / "factory.db"}"\n')
    assert run(capsys, "--config", str(config), "pin", A)[0] == 0
    assert run(capsys, "--config", str(config), "pin", "--clear")[0] == 0
    assert not (home / "state").exists()


def test_clear_removes_the_pin_then_says_already(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = make_pin(home, A, "factory-v0.2.0")  # no install needed: the pin is removed, not checked
    assert run(capsys, "pin", "--clear") == (0, ["Pin cleared (was 3f2a9c4e1b07 (factory-v0.2.0)); tl runs the install it is "
                                                 "started from", f"{EFFECT} If rounds or attempts still run: tl pin factory-v0.2.0 "
                                                 "back, drain, then make this change again."], "")
    assert not path.exists() and sorted(child.name for child in path.parent.iterdir()) == []
    assert run(capsys, "pin", "--clear") == (0, ["Pin cleared: already"], "")


def test_clear_removes_an_invalid_pin(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = default_pin(home)
    path.parent.mkdir(parents=True)
    path.write_text("format = 2\n")
    assert run(capsys, "pin", "--clear")[1] == ["Pin cleared (was invalid (format is 2, not 1)); tl runs the install it is started from",
                                                f"{EFFECT} The earlier pin was invalid: nothing to go back to."]
    assert not path.exists()


def test_pinning_over_an_invalid_pin_replaces_it(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_install(home, A)
    path = default_pin(home)
    path.parent.mkdir(parents=True)
    path.write_text("not toml [")
    code, out, _err = run(capsys, "pin", A)
    assert code == 0 and out[1].startswith("Was: invalid (not TOML: ")
    assert isinstance(read(FILES, path), Pin)


@pytest.mark.parametrize("failing", ["write", "replace"])
def test_a_failed_write_is_unavailable_and_keeps_the_old_pin(home: Path, failing: str) -> None:
    make_install(home, A)
    path = make_pin(home, B)
    found = pin_op.pin(Refusing(failing=failing), home, None, A, NOW)
    assert isinstance(found, pin_op.Unavailable) and found.word == "write" and found.detail.endswith("the pin is unchanged")
    assert read(FILES, path) == Pin(B, None, "2026-11-20T10:05:00Z")
    assert sorted(child.name for child in path.parent.iterdir()) == [path.name]


def test_an_unmakeable_config_folder_is_unavailable_exit_3(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_install(home, A)
    (home / ".config").write_text("a file where the folder belongs")
    code, _out, err = run(capsys, "pin", A)
    assert code == 3 and err.startswith("tl pin: unavailable write: ")


@pytest.mark.parametrize("argv", [["pin"], ["pin", A, "--clear"]])
def test_exactly_one_of_rev_and_clear_is_a_usage_rule(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(argv)
    assert stopped.value.code == 2 and "tl pin" in capsys.readouterr().err


def test_a_manifest_alone_decides_completeness_not_the_lock(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """While `tl install` holds the lock and has written no manifest, pin and resolver both say incomplete."""
    (installs_root(home) / A / "venv" / "bin").mkdir(parents=True)
    (installs_root(home) / f"{A}.lock").write_text("held")
    assert run(capsys, "pin", A)[2].startswith("tl pin: refused incomplete: ")
    make_install(home, B)
    make_pin(home, A)
    assert start.resolve(["step", "list"], home, "/launcher/python", FILES) == start.PinRefused(
        "pin:incomplete", A, f"pinned 3f2a9c4e1b07 at {installs_root(home) / A} has no manifest (an install never finished, or is "
        "still building); wait for it, or tl pin --clear")
    assert not (installs_root(home) / A / MANIFEST).exists()


def test_a_moved_tag_whose_other_install_is_broken_is_still_ambiguous(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The tag was moved: B's install records it too, but B's python is gone. The tag names two installs either way."""
    make_install(home, A, "factory-v0.2.0")
    python_of(make_install(home, B, "factory-v0.2.0")).unlink()
    code, _out, err = run(capsys, "pin", "factory-v0.2.0")
    assert code == 1 and err == (f"tl pin: refused ambiguous: tag factory-v0.2.0 is recorded by 2 installs ({A}, {B} (broken)); "
                                 "tl pin COMMIT\n")
    assert not default_pin(home).exists()


def test_a_tag_recorded_only_by_a_broken_install_is_broken(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    python_of(make_install(home, B, "factory-v0.2.0")).unlink()
    code, _out, err = run(capsys, "pin", "factory-v0.2.0")
    assert code == 1 and err.startswith(f"tl pin: refused broken: {installs_root(home) / B} is broken (")


def test_a_tag_matches_exactly_case_included(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_install(home, A, "factory-v0.2.0")
    code, _out, err = run(capsys, "pin", "Factory-V0.2.0")
    assert code == 1 and err.startswith("tl pin: refused not_installed: no install under ")


class Unlistable(LocalFiles):
    def names(self, folder: Path) -> tuple[str, ...]:
        raise PermissionError(13, "Permission denied", str(folder))


def test_an_installs_folder_that_cannot_be_listed_is_typed_not_a_traceback(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    found = pin_op.pin(Unlistable(), home, None, "factory-v0.2.0", NOW)
    assert isinstance(found, pin_op.Unavailable) and found.word == "read" and "Permission denied" in found.detail
    installs_root(home).parent.mkdir(parents=True)
    installs_root(home).write_text("a file where the installs folder belongs")
    code, _out, err = run(capsys, "pin", "factory-v0.2.0")
    assert code == 1 and err == f"tl pin: refused broken: {installs_root(home)} is not a directory\n"
    assert not default_pin(home).exists()
