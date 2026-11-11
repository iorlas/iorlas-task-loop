"""Real layer: the environment folders on the real file system (`RealEnvFiles`) and one setup command through the shelf's
registered start (`setup_process`, `setup_seen`): links are removed, never followed; an unreadable directory is emptied
through the `onexc` retry; a command's identity is registered before it runs, its output and exit come back, and a
process left in its group is seen."""

import os
import stat
from pathlib import Path

from stream_proc import OwnedProcess, group_alive

from taskloop.composition import RealEnvFiles, setup_process, setup_seen


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


def test_empty_removes_directories_an_agent_made_unreadable(tmp_path: Path) -> None:
    folder = tmp_path / "cache"
    (folder / "a" / "locked" / "deep").mkdir(parents=True)
    (folder / "a" / "locked" / "deep" / "f").write_text("x")
    (folder / "top").mkdir()
    (folder / "a" / "locked").chmod(0)
    (folder / "top").chmod(0)
    assert RealEnvFiles().empty(folder)
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_empty_of_a_missing_folder_is_true_and_of_a_link_false(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "f").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    files = RealEnvFiles()
    assert files.empty(tmp_path / "missing")
    assert not files.empty(tmp_path / "link") and (tmp_path / "real" / "f").exists()


def test_ensure_creates_0700_and_refuses_a_link_in_place_of_a_folder(tmp_path: Path) -> None:
    files = RealEnvFiles()
    made = tmp_path / ".env" / "s1" / "uv-cache"
    assert files.ensure(made) and stat.S_IMODE(made.stat().st_mode) == 0o700
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / ".t").mkdir()
    (tmp_path / ".t" / "s1").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    assert not files.ensure(tmp_path / ".t" / "s1")


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
