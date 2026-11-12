"""The owner pin file beside the machine config in use: its place, reader, atomic writer and clear (tl-8bh9.8.3 4.4)."""

import tomllib
from pathlib import Path

import pytest
from install_doubles import NOW, A, B, Refusing

from taskloop.installs import LocalFiles
from taskloop.pin_file import Pin, PinInvalid, clear, pin_path, read, write

FILES = LocalFiles()


def test_the_default_pin_is_beside_the_default_machine_config(tmp_path: Path) -> None:
    assert pin_path(None, tmp_path) == tmp_path / ".config/task-loop/config.pin.toml"


def test_two_configs_in_one_folder_have_two_pins(tmp_path: Path) -> None:
    assert pin_path(str(tmp_path / "m" / "a.toml"), tmp_path) == tmp_path / "m" / "a.pin.toml"
    assert pin_path(str(tmp_path / "m" / "b.toml"), tmp_path) == tmp_path / "m" / "b.pin.toml"


def test_a_relative_config_is_made_absolute_as_the_config_reader_does(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert pin_path("install", Path("/home/u")) == tmp_path / "install.pin.toml"


@pytest.mark.parametrize("config", ["/", ""])
def test_a_config_path_without_a_name_has_no_pin_file(config: str) -> None:
    assert pin_path(config, Path("/home/u")) is None


def test_the_writer_round_trips_through_the_reader_and_tomllib(tmp_path: Path) -> None:
    path = tmp_path / "config.pin.toml"
    assert write(FILES, path, A, "factory-v0.2.0", NOW) == Pin(A, "factory-v0.2.0", "2026-11-20T10:05:00Z")
    assert tomllib.loads(path.read_text()) == {"format": 1, "commit": A, "tag": "factory-v0.2.0", "pinned_at": "2026-11-20T10:05:00Z"}
    assert read(FILES, path) == Pin(A, "factory-v0.2.0", "2026-11-20T10:05:00Z")
    write(FILES, path, B, None, NOW)
    assert read(FILES, path) == Pin(B, None, "2026-11-20T10:05:00Z")
    assert sorted(child.name for child in tmp_path.iterdir()) == ["config.pin.toml"]


@pytest.mark.parametrize(("commit", "tag"), [(A[:12], None), (A.upper(), None), (A, 'x"y')])
def test_the_writer_refuses_what_it_does_not_write(tmp_path: Path, commit: str, tag: str | None) -> None:
    with pytest.raises(ValueError):
        write(FILES, tmp_path / "config.pin.toml", commit, tag, NOW)
    assert not (tmp_path / "config.pin.toml").exists()


@pytest.mark.parametrize("failing", ["write", "replace"])
def test_a_failed_write_keeps_the_old_pin(tmp_path: Path, failing: str) -> None:
    path = tmp_path / "config.pin.toml"
    write(FILES, path, A, None, NOW)
    with pytest.raises(OSError):
        write(Refusing(failing=failing), path, B, None, NOW)
    assert read(FILES, path) == Pin(A, None, "2026-11-20T10:05:00Z")


def test_no_file_is_no_pin_and_clear_of_an_absent_file_says_so(tmp_path: Path) -> None:
    path = tmp_path / "config.pin.toml"
    assert read(FILES, path) is None
    assert clear(FILES, path) is False
    write(FILES, path, A, None, NOW)
    assert clear(FILES, path) is True
    assert read(FILES, path) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("text", "detail"), [
    ("commit = ", "not TOML"),
    (f'format = 1\ncommit = "{A}"\npinned_at = "t"\nbacklog = "x"\n', "unknown key backlog"),
    (f'format = 2\ncommit = "{A}"\npinned_at = "t"\n', "format is 2, not 1"),
    (f'format = true\ncommit = "{A}"\npinned_at = "t"\n', "format is True, not 1"),
    (f'format = 1\ncommit = "{A[:12]}"\npinned_at = "t"\n', "is not a full commit id"),
    ('format = 1\npinned_at = "t"\n', "commit is missing"),
    (f'format = 1\ncommit = "{A}"\n', "pinned_at is missing"),
    (f'format = 1.0\ncommit = "{A}"\npinned_at = "t"\n', "format is 1.0, not 1"),
    (f'format = 1\ncommit = "{A}"\ntag = "a b"\npinned_at = "t"\n', "tag 'a b' is not a tag name"),
], ids=["toml", "unknown_key", "format", "format_bool", "short_id", "no_commit", "no_time", "format_float", "bad_tag"])
def test_an_invalid_pin_says_why(tmp_path: Path, text: str, detail: str) -> None:
    path = tmp_path / "config.pin.toml"
    path.write_text(text)
    found = read(FILES, path)
    assert isinstance(found, PinInvalid) and detail in found.detail


def test_an_unreadable_pin_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "config.pin.toml"
    write(FILES, path, A, None, NOW)
    assert read(Refusing(unreadable=path), path) == PinInvalid("unreadable: PermissionError")
    path.write_bytes(b"\xff\xfe")
    assert read(FILES, path) == PinInvalid("unreadable: UnicodeDecodeError")
