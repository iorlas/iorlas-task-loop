"""`tl version [--json]`: which install runs (this process's prefix) and which is pinned for the machine config in use;
read-only, no lock or temp file read (tl-8bh9.8.3 section 6.3)."""

import json
import sys
from pathlib import Path

import pytest
from install_doubles import A, B, make_install, make_pin

from taskloop.cli import main
from taskloop.cli_install import data, describe, lines
from taskloop.installs import MANIFEST, LocalFiles, installs_root

FILES = LocalFiles()


def test_a_managed_process_with_its_pin(tmp_path: Path) -> None:
    install = make_install(tmp_path, A, "factory-v0.2.0")
    pin = make_pin(tmp_path, A, "factory-v0.2.0")
    found = describe(install / "venv", tmp_path, None, FILES)
    venv = (install / "venv").resolve()
    assert lines(found) == [f"Running: 3f2a9c4e1b07 (factory-v0.2.0) ({venv})",
                            f"Pinned: 3f2a9c4e1b07 (factory-v0.2.0) since 2026-11-20T10:05:00Z ({pin})"]
    assert data(found) == {"running": {"prefix": str(venv), "install": A, "tag": "factory-v0.2.0"},
                           "pinned": {"commit": A, "tag": "factory-v0.2.0", "pinned_at": "2026-11-20T10:05:00Z", "file": str(pin)}}


def test_an_unmanaged_unpinned_process(tmp_path: Path) -> None:
    runner = tmp_path / "runner" / ".venv"
    found = describe(runner, tmp_path, None, FILES)
    assert lines(found) == [f"Running: unmanaged ({runner})", "Pinned: none"]
    assert data(found) == {"running": {"prefix": str(runner), "install": None, "tag": None}, "pinned": None}


@pytest.mark.parametrize("damage", ["incomplete", "broken"])
def test_a_prefix_without_a_complete_install_beside_it_is_unmanaged(tmp_path: Path, damage: str) -> None:
    install = make_install(tmp_path, A)
    if damage == "incomplete":
        (install / MANIFEST).unlink()
    else:
        (install / MANIFEST).write_text("format = 2\n")
    assert lines(describe(install / "venv", tmp_path, None, FILES))[0] == f"Running: unmanaged ({(install / 'venv').resolve()})"


def test_a_linked_prefix_resolves_to_its_install(tmp_path: Path) -> None:
    install = make_install(tmp_path, A, "factory-v0.2.0")
    link = tmp_path / "bin-link" / "venv"
    link.parent.mkdir()
    link.symlink_to(install / "venv")
    found = describe(link, tmp_path, None, FILES)
    assert data(found)["running"] == {"prefix": str((install / "venv").resolve()), "install": A, "tag": "factory-v0.2.0"}


def test_a_complete_install_outside_this_homes_installs_root_is_unmanaged(tmp_path: Path) -> None:
    install = make_install(tmp_path / "other-home", A)
    found = describe(install / "venv", tmp_path, None, FILES)
    assert found.running is None and lines(found)[0].startswith("Running: unmanaged")


def test_a_config_path_without_a_name_reports_an_invalid_pin(tmp_path: Path) -> None:
    found = describe(tmp_path / "runner", tmp_path, "/", FILES)
    assert lines(found)[1] == "Pinned: invalid (--config '/' names no file, so it has no pin file)"
    assert data(found)["pinned"] == {"invalid": "--config '/' names no file, so it has no pin file", "file": None}


def test_an_invalid_pin_is_reported_not_refused(tmp_path: Path) -> None:
    pin = tmp_path / "m" / "config.pin.toml"
    pin.parent.mkdir()
    pin.write_text("format = 2\n")
    found = describe(tmp_path / "runner", tmp_path, str(tmp_path / "m" / "config.toml"), FILES)
    assert lines(found)[1] == f"Pinned: invalid ({pin})"
    assert data(found)["pinned"] == {"invalid": "format is 2, not 1", "file": str(pin)}


def test_the_pin_follows_the_config_in_use(tmp_path: Path) -> None:
    make_pin(tmp_path, A)
    other = make_pin(tmp_path, B, config=str(tmp_path / "m" / "b.toml"))
    found = describe(tmp_path / "runner", tmp_path, str(tmp_path / "m" / "b.toml"), FILES)
    assert lines(found)[1] == f"Pinned: 9b1e07d2aa31 since 2026-11-20T10:05:00Z ({other})"


def test_a_lock_and_a_temp_file_change_nothing(tmp_path: Path) -> None:
    install = make_install(tmp_path, A)
    make_pin(tmp_path, A)
    before = data(describe(install / "venv", tmp_path, None, FILES))
    (installs_root(tmp_path) / f"{A}.lock").write_text("held")
    (install / f"{MANIFEST}.tmp").write_text("format = 2\n")
    (tmp_path / ".config/task-loop/config.pin.toml.tmp").write_text("format = 2\n")
    assert data(describe(install / "venv", tmp_path, None, FILES)) == before


@pytest.mark.parametrize("json_output", [False, True])
def test_the_command_reads_this_process_and_the_homes_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                          capsys: pytest.CaptureFixture[str], json_output: bool) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    pin = make_pin(tmp_path, A, "factory-v0.2.0")
    prefix = Path(sys.prefix).resolve()
    assert main(["version", "--json"] if json_output else ["version"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    if json_output:
        assert json.loads(output.out) == {"running": {"prefix": str(prefix), "install": None, "tag": None},
                                          "pinned": {"commit": A, "tag": "factory-v0.2.0", "pinned_at": "2026-11-20T10:05:00Z",
                                                     "file": str(pin)}}
    else:
        assert output.out == (f"Running: unmanaged ({prefix})\n"
                              f"Pinned: 3f2a9c4e1b07 (factory-v0.2.0) since 2026-11-20T10:05:00Z ({pin})\n")


def test_the_command_honours_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    make_pin(tmp_path, A)
    assert main(["--config", str(tmp_path / "scratch.toml"), "version"]) == 0  # no config file needed: nothing else is read
    assert capsys.readouterr().out.endswith("Pinned: none\n")
