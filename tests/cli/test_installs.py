"""`installs.state`, the one validity rule every install command uses, and the manifest's writer (tl-8bh9.8.3 4.3)."""

import tomllib
from pathlib import Path

import pytest
from install_doubles import A, B, Refusing, make_install

from taskloop.installs import (
    MANIFEST,
    LocalFiles,
    Manifest,
    State,
    atomic_write,
    installs_root,
    is_tag,
    manifest_text,
    python_of,
    state,
)

FILES = LocalFiles()


def test_the_installs_root_is_fixed_under_the_home(tmp_path: Path) -> None:
    assert installs_root(tmp_path) == tmp_path / ".local/share/task-loop/installs"


def test_a_complete_install_carries_its_manifest(tmp_path: Path) -> None:
    make_install(tmp_path, A, "factory-v0.2.0")
    assert state(FILES, installs_root(tmp_path), A) == State(
        "complete", Manifest(A, "factory-v0.2.0", "2026-11-20T10:00:00Z", "/home/u/src/task-loop"))
    make_install(tmp_path, B)
    found = state(FILES, installs_root(tmp_path), B)
    assert found.word == "complete" and found.manifest is not None and found.manifest.tag is None


def test_no_directory_is_absent_and_a_directory_without_manifest_is_incomplete(tmp_path: Path) -> None:
    root = installs_root(tmp_path)
    assert state(FILES, root, A) == State("absent")
    (root / B / "venv").mkdir(parents=True)
    assert state(FILES, root, B) == State("incomplete")


def test_only_a_full_commit_names_an_install(tmp_path: Path) -> None:
    make_install(tmp_path, A)
    assert state(FILES, installs_root(tmp_path), A[:12]).word == "absent"
    assert state(FILES, installs_root(tmp_path), A.upper()).word == "absent"


def manifest(**values: object) -> str:
    keys = {"format": 1, "commit": A, "installed_at": "2026-11-20T10:00:00Z", "checkout": "/c"} | values
    return "".join(f"{key} = {value!r}\n".replace("'", '"') for key, value in keys.items() if value is not None)


@pytest.mark.parametrize(("text", "detail"), [
    ("format = 1\ncommit = ", "not TOML"),
    (manifest(extra="x"), "unknown key extra"),
    (manifest(format=2), "format is 2, not 1"),
    (manifest(format="1"), "format is '1', not 1"),
    ("format = 1.0\n" + manifest(format=None), "format is 1.0, not 1"),
    ("format = true\n" + manifest(format=None), "format is True, not 1"),
    (manifest(tag="bad tag"), "tag 'bad tag' is not a tag name"),
    (manifest(checkout=None), "checkout is missing"),
    (manifest(tag=3), "tag is missing or not a string"),
    (manifest(commit=B), f"manifest names commit {B}"),
], ids=["toml", "unknown_key", "format", "format_type", "format_float", "format_bool", "bad_tag", "missing_key", "tag_type",
        "other_commit"])
def test_a_manifest_that_fails_any_condition_is_broken(tmp_path: Path, text: str, detail: str) -> None:
    make_install(tmp_path, A, manifest=text)
    found = state(FILES, installs_root(tmp_path), A)
    assert found.word == "broken" and found.manifest is None
    assert detail in found.detail


@pytest.mark.parametrize("thing", ["file", "dangling_link", "unexaminable"])
def test_anything_but_a_directory_at_the_install_is_broken(tmp_path: Path, thing: str) -> None:
    root = installs_root(tmp_path)
    root.mkdir(parents=True)
    files: LocalFiles = Refusing(unexaminable=root / A) if thing == "unexaminable" else FILES
    if thing == "file":
        (root / A).write_text("")
    if thing == "dangling_link":
        (root / A).symlink_to(tmp_path / "moved-away")
    found = state(files, root, A)
    detail = {"file": "is not a directory", "dangling_link": "is a link to nothing", "unexaminable": "cannot be examined"}[thing]
    assert found == State("broken", detail=f"{root / A} {detail}")


@pytest.mark.parametrize("thing", ["dangling_link", "directory", "unexaminable"])
def test_anything_but_a_file_at_the_manifest_is_broken(tmp_path: Path, thing: str) -> None:
    install = make_install(tmp_path, A)
    manifest_path = install / MANIFEST
    manifest_path.unlink()
    files: LocalFiles = Refusing(unexaminable=manifest_path) if thing == "unexaminable" else FILES
    if thing == "dangling_link":
        manifest_path.symlink_to(install / "gone.toml")
    if thing == "directory":
        manifest_path.mkdir()
    detail = {"dangling_link": "is a link to nothing", "directory": "is not a file", "unexaminable": "cannot be examined"}[thing]
    assert state(files, installs_root(tmp_path), A) == State("broken", detail=f"{manifest_path} {detail}")


def test_an_unreadable_manifest_is_broken(tmp_path: Path) -> None:
    install = make_install(tmp_path, A)
    assert state(Refusing(unreadable=install / MANIFEST), installs_root(tmp_path), A) == State(
        "broken", detail="manifest unreadable: PermissionError")


@pytest.mark.parametrize("damage", ["absent", "not_executable", "dangling_link", "directory"])
def test_a_manifest_without_a_runnable_python_is_broken(tmp_path: Path, damage: str) -> None:
    python = python_of(make_install(tmp_path, A))
    python.unlink()
    if damage == "not_executable":
        python.write_text("")
        python.chmod(0o644)
    if damage == "dangling_link":
        python.symlink_to(tmp_path / "uv-python-3.15.0" / "bin" / "python3.15")
    if damage == "directory":
        python.mkdir()
    found = state(FILES, installs_root(tmp_path), A)
    assert found.word == "broken" and "is not an executable file" in found.detail


def test_python_may_be_a_link_to_an_executable(tmp_path: Path) -> None:
    python = python_of(make_install(tmp_path, A))
    target = tmp_path / "cpython" / "python3.15"
    target.parent.mkdir()
    python.rename(target)
    python.symlink_to(target)
    assert state(FILES, installs_root(tmp_path), A).word == "complete"


def test_the_manifest_round_trips_through_tomllib_with_an_escaped_path() -> None:
    checkout = 'C:\\odd "dir"\n\tend\x7f'
    text = manifest_text(Manifest(A, "release/factory-v0.2.0", "2026-11-20T10:00:00Z", checkout))
    assert tomllib.loads(text) == {"format": 1, "commit": A, "tag": "release/factory-v0.2.0",
                                   "installed_at": "2026-11-20T10:00:00Z", "checkout": checkout}
    assert "tag" not in tomllib.loads(manifest_text(Manifest(A, None, "t", "/c")))


@pytest.mark.parametrize(("commit", "tag"), [(A[:12], None), (A, "bad tag"), (A, "-x"), (A, "a..b"), (A, "x.lock"), (A, ".x"),
                                             (A, "a//b"), (A, "a/"), (A, "x.")])
def test_the_writer_refuses_a_value_it_does_not_write(commit: str, tag: str | None) -> None:
    with pytest.raises(ValueError):
        manifest_text(Manifest(commit, tag, "t", "/c"))


def test_tag_names_follow_the_ref_rules() -> None:
    assert all(is_tag(name) for name in ("factory-v0.2.0", "v1", "release/v1_2", "a.b"))


@pytest.mark.parametrize("failing", ["write", "replace"])
def test_a_failed_atomic_write_leaves_the_old_file_and_no_debris(tmp_path: Path, failing: str) -> None:
    path = tmp_path / "install.toml"
    path.write_text("old\n")
    with pytest.raises(OSError):
        atomic_write(Refusing(failing=failing), path, "new\n")
    assert path.read_text() == "old\n"
    assert [child.name for child in tmp_path.iterdir()] == ["install.toml"]
    atomic_write(FILES, path, "new\n")
    assert path.read_text() == "new\n"
    assert [child.name for child in tmp_path.iterdir()] == ["install.toml"]


class Interleaved(LocalFiles):
    """A second writer of the same file runs between this writer's temporary file and its rename."""

    def __init__(self) -> None:
        self.temporaries: list[Path] = []

    def replace(self, source: Path, target: Path) -> None:
        self.temporaries.append(source)
        if len(self.temporaries) == 1:
            atomic_write(self, target, "second\n")
        super().replace(source, target)


def test_two_writers_never_share_a_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "config.pin.toml"
    files = Interleaved()
    atomic_write(files, path, "first\n")
    first, second = files.temporaries
    assert first != second and first.parent == second.parent == tmp_path
    assert path.read_text() == "first\n"  # the outer rename came last; each file whole
    assert [child.name for child in tmp_path.iterdir()] == ["config.pin.toml"]
