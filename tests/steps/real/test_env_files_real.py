"""Real layer: the environment folders on the real file system (`RealEnvFiles`) and one setup command through the shelf's
registered start (`setup_process`, `setup_seen`): links are removed, never followed; an unreadable directory is emptied
through the `onexc` retry; a command's identity is registered before it runs, its output and exit come back, and a
process left in its group is seen."""

import os
import stat
from pathlib import Path

import pytest
from stream_proc import OwnedProcess, group_alive

from taskloop import slot_env
from taskloop.owned_processes import setup_seen
from taskloop.slot_env import RealEnvFiles, setup_process


def test_empty_removes_a_planted_link_never_its_target(tmp_path: Path) -> None:
    folder, outside = tmp_path / "tmp", tmp_path / "outside"
    (outside / "keep").mkdir(parents=True)
    (outside / "keep" / "file").write_text("mine")
    folder.mkdir()
    (folder / "link").symlink_to(outside)
    (folder / "dir-link").symlink_to(outside / "keep", target_is_directory=True)
    (folder / "file").write_text("x")
    assert RealEnvFiles().empty(folder)
    assert list(folder.iterdir()) == [] and (outside / "keep" / "file").read_text() == "mine"


def test_empty_removes_directories_an_agent_made_unreadable_or_read_only(tmp_path: Path) -> None:
    """0o000 folders, nested ones, and read-only (0o500) folders holding files and a 0o000 folder: all removed."""
    folder = tmp_path / "cache"
    (folder / "a" / "locked" / "deep" / "deeper").mkdir(parents=True)
    (folder / "a" / "locked" / "deep" / "deeper" / "f").write_text("x")
    (folder / "top").mkdir()
    (folder / "ro" / "sealed").mkdir(parents=True)
    for name in ("one", "two"):
        (folder / "ro" / name).write_text("x")
    (folder / "a" / "locked" / "deep" / "deeper").chmod(0)
    (folder / "a" / "locked" / "deep").chmod(0)
    (folder / "a" / "locked").chmod(0)
    (folder / "top").chmod(0)
    (folder / "ro" / "sealed").chmod(0)
    (folder / "ro").chmod(0o500)
    assert RealEnvFiles().empty(folder)
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_empty_of_a_folder_an_agent_made_read_only_removes_its_entries(tmp_path: Path) -> None:
    folder = tmp_path / "tmp"
    folder.mkdir()
    (folder / "file").write_text("x")
    folder.chmod(0o500)
    assert RealEnvFiles().empty(folder)
    assert list(folder.iterdir()) == []


def test_empty_goes_on_past_an_entry_that_vanished_meanwhile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "tmp"
    folder.mkdir()
    for name in ("a", "b", "c"):
        (folder / name).write_text("x")
    removing = slot_env._remove

    def racing(path: str, retry: slot_env._Writable) -> None:
        (folder / "b").unlink(missing_ok=True)  # another remover was first
        removing(path, retry)

    monkeypatch.setattr(slot_env, "_remove", racing)
    assert RealEnvFiles().empty(folder)
    assert list(folder.iterdir()) == []


def test_empty_of_a_missing_folder_is_true_and_of_a_link_false(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "f").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    files = RealEnvFiles()
    assert files.empty(tmp_path / "missing")
    assert not files.empty(tmp_path / "link") and (tmp_path / "real" / "f").exists()


def test_ensure_makes_0700_again_and_refuses_a_link_in_place_of_a_folder(tmp_path: Path) -> None:
    files = RealEnvFiles()
    made = tmp_path / ".env" / "s1" / "uv-cache"
    assert files.ensure(made) and stat.S_IMODE(made.stat().st_mode) == 0o700
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere").chmod(0o755)
    (tmp_path / ".t").mkdir()
    (tmp_path / ".t" / "s1").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    assert not files.ensure(tmp_path / ".t" / "s1")
    assert stat.S_IMODE((tmp_path / "elsewhere").stat().st_mode) == 0o755  # the link's target is never chmodded
    made.chmod(0o500)  # an agent made its root read-only
    assert files.ensure(made) and stat.S_IMODE(made.stat().st_mode) == 0o700


def test_the_release_empties_the_scratch_only_where_it_belongs(tmp_path: Path) -> None:
    """`.t` replaced by a link to another slot: nothing there is touched; the real scratch is emptied."""
    base = tmp_path / "slots" / "0123456789ab"
    (base / "s2" / "s1").mkdir(parents=True)
    (base / "s2" / "s1" / "work").write_text("another slot's")
    (base / ".t").symlink_to(base / "s2", target_is_directory=True)
    files = RealEnvFiles()
    assert not files.empty_scratch(base / "s1") and (base / "s2" / "s1" / "work").read_text() == "another slot's"
    (base / ".t").unlink()
    (base / ".t" / "s1").mkdir(parents=True)
    (base / ".t" / "s1" / "left").write_text("x")
    assert files.empty_scratch(base / "s1") and list((base / ".t" / "s1").iterdir()) == []


def test_a_command_registers_before_it_runs_and_its_output_and_exit_come_back(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    registered: list[tuple[OwnedProcess, bool]] = []
    lines: list[bytes] = []
    ended = setup_process(
        ["/bin/sh", "-c", f"touch {marker}; echo out; echo err >&2; exit 3"],
        registered=lambda process: registered.append((process, marker.exists())), cwd=str(tmp_path),
        env={"PATH": os.environ["PATH"]}, timeout=30, line=lines.append,
    )
    assert (ended.rc, ended.timed_out, ended.exec_failed, ended.uncertain) == (3, False, False, False)
    assert len(registered) == 1 and registered[0][1] is False and registered[0][0].pgid == ended.pgid
    assert sorted(lines) == [b"err\n", b"out\n"]
    assert setup_seen(registered[0][0]) == "gone"


def test_a_command_that_cannot_exec_never_ran(tmp_path: Path) -> None:
    ended = setup_process([str(tmp_path / "missing")], registered=lambda _process: None, cwd=str(tmp_path), env={}, timeout=30,
                          line=lambda _line: None)
    assert ended.exec_failed and ended.rc is None


def test_a_process_left_in_the_group_is_seen(tmp_path: Path) -> None:
    """The background `sleep` ends by itself within two seconds; nothing is signalled."""
    registered: list[OwnedProcess] = []
    ended = setup_process(["/bin/sh", "-c", "sleep 2 >/dev/null 2>&1 & exit 0"], registered=registered.append, cwd=str(tmp_path),
                          env={"PATH": os.environ["PATH"]}, timeout=30, line=lambda _line: None)
    assert ended.rc == 0 and group_alive(ended.pgid)
    assert setup_seen(registered[0]) == "alive"
