"""Installs under the per-user folder: the layout, the manifest's one validity rule (`state`) and the file port.

An install is `<home>/.local/share/task-loop/installs/<commit>/` with `venv/bin/python` and a manifest `install.toml`,
written last by atomic rename; its presence means "complete" (tl-8bh9.8.3 sections 4.1-4.3). Imported before the CLI by
`start`: the standard library only, never a factory module (`pin_file` imports this one).
"""

import os
import re
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, Protocol

MANIFEST: Final = "install.toml"
COMMIT: Final = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
TAG: Final = re.compile(r"[A-Za-z0-9._/-]+")
type Word = Literal["absent", "incomplete", "broken", "complete"]
type Kind = Literal["absent", "dangling", "directory", "file", "other", "unexaminable"]  # `unexaminable`: stat failed


class Reads(Protocol):
    """The reads the resolver, `tl version` and every validity check make; no lock, no listing."""

    def read_text(self, path: Path) -> str: ...  # OSError when unreadable, FileNotFoundError when absent
    def kind(self, path: Path) -> Kind: ...  # what is there, following links (a link to nothing is `dangling`)
    def runnable(self, path: Path) -> bool: ...  # a file, executable, after following links


class Writes(Protocol):
    """The writes of the manifest and the pin file: a new synced file, an atomic rename, a removal, a folder sync."""

    def write_temporary(self, folder: Path, name: str, text: str) -> Path: ...  # a new unique file; none left on failure
    def replace(self, source: Path, target: Path) -> None: ...
    def remove(self, path: Path) -> bool: ...  # False when there was nothing to remove
    def sync_folder(self, folder: Path) -> None: ...


class LocalFiles:
    """This machine's file system, through `os` only."""

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def kind(self, path: Path) -> Kind:
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            return "dangling" if path.is_symlink() else "absent"
        except OSError:
            return "unexaminable"
        return "directory" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "other"

    def runnable(self, path: Path) -> bool:
        return path.is_file() and os.access(path, os.X_OK)

    def write_temporary(self, folder: Path, name: str, text: str) -> Path:
        descriptor, made = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=folder)  # O_EXCL, 0600
        try:
            self.fill(descriptor, text.encode())
        except BaseException:
            os.unlink(made)
            raise
        return Path(made)

    def fill(self, descriptor: int, data: bytes) -> None:
        """Write all of `data`, sync and close the descriptor."""
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def replace(self, source: Path, target: Path) -> None:
        os.replace(source, target)

    def names(self, folder: Path) -> tuple[str, ...]:
        """The entries' names in `folder`, none when it does not exist (`tl pin TAG`'s one listing of the installs)."""
        try:
            return tuple(sorted(os.listdir(folder)))
        except FileNotFoundError:
            return ()

    def make_folder(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)

    def remove(self, path: Path) -> bool:
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def sync_folder(self, folder: Path) -> None:
        descriptor = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class Manifest:
    commit: str
    tag: str | None
    installed_at: str
    checkout: str


@dataclass(frozen=True)
class State:
    word: Word
    manifest: Manifest | None = None  # only when complete
    detail: str = ""  # why broken


def installs_root(home: Path) -> Path:
    """The fixed installs root: no config key, no environment variable."""
    return home / ".local" / "share" / "task-loop" / "installs"


def running(files: Reads, prefix: Path, home: Path) -> Manifest | None:
    """The complete install under this home's installs root whose `venv` is `prefix` (both resolved); None: unmanaged.
    `tl version` and the rounds' `rounds install` line read it."""
    resolved, root = prefix.resolve(), installs_root(home).resolve()
    if resolved.name != "venv" or resolved.parent.parent != root:
        return None
    return state(files, root, resolved.parent.name).manifest


def python_of(install: Path) -> Path:
    return install / "venv" / "bin" / "python"


def is_commit(text: str) -> bool:
    """A full commit id: 40 or 64 lowercase hex."""
    return COMMIT.fullmatch(text) is not None


def is_tag(name: str) -> bool:
    """A tag name the manifest records: `[A-Za-z0-9._/-]` under Git's ref-name rules."""
    parts = name.split("/")
    return (TAG.fullmatch(name) is not None and ".." not in name and not name.startswith("-") and not name.endswith((".", ".lock"))
            and all(part and not part.startswith(".") and not part.endswith(".lock") for part in parts))


def basic_string(value: str) -> str:
    """A TOML basic string: `\\`, `"` and control characters escaped."""
    escaped = "".join(f"\\u{ord(char):04x}" if ord(char) < 0x20 or ord(char) == 0x7F else char
                      for char in value.replace("\\", "\\\\").replace('"', '\\"'))
    return f'"{escaped}"'


def utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write(files: Writes, path: Path, text: str) -> None:
    """Written to a new unique `.<name>.*.tmp` beside `path`, synced, renamed over `path`, the folder synced: a reader sees
    the old file or the whole new one, and two writers never share a temporary file. Any failure leaves `path` as it was
    and removes the temporary file."""
    temporary = files.write_temporary(path.parent, path.name, text)
    try:
        files.replace(temporary, path)
    except BaseException:
        files.remove(temporary)
        raise
    files.sync_folder(path.parent)


def manifest_text(manifest: Manifest) -> str:
    """The fixed formatter over validated values; ValueError for a value it does not write."""
    if not is_commit(manifest.commit) or (manifest.tag is not None and not is_tag(manifest.tag)):
        raise ValueError(f"not a manifest: {manifest.commit!r} {manifest.tag!r}")
    tag = "" if manifest.tag is None else f"tag = {basic_string(manifest.tag)}\n"
    return (f"format = 1\ncommit = {basic_string(manifest.commit)}\n{tag}installed_at = {basic_string(manifest.installed_at)}\n"
            f"checkout = {basic_string(manifest.checkout)}\n")


def _strings(table: dict[str, object], required: tuple[str, ...], optional: tuple[str, ...]) -> dict[str, str] | str:
    """The table's values when its keys are exactly `format` = 1, the required ones and some optional ones, all strings;
    else why not."""
    unknown = sorted(set(table) - {"format", *required, *optional})
    if unknown:
        return f"unknown key {unknown[0]}"
    format_ = table.get("format")
    if type(format_) is not int or format_ != 1:
        return f"format is {format_!r}, not 1"
    found: dict[str, str] = {}
    for key in (*required, *optional):
        value = table.get(key)
        if value is None and key in optional:
            continue
        if not isinstance(value, str):
            return f"{key} is missing or not a string"
        found[key] = value
    return found


def parse_table(text: str, required: tuple[str, ...], optional: tuple[str, ...]) -> dict[str, str] | str:
    """A strict small TOML file (the manifest, the pin): its string values, a `tag` a tag name; or why it is not one."""
    try:
        table = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return f"not TOML: {error}"
    found = _strings(table, required, optional)
    if isinstance(found, dict) and "tag" in found and not is_tag(found["tag"]):
        return f"tag {found['tag']!r} is not a tag name"
    return found


def _valid(files: Reads, install: Path, text: str) -> Manifest | str:
    """The manifest when it has exactly its keys, `format = 1`, the directory's commit and a runnable python; else why not."""
    found = parse_table(text, ("commit", "installed_at", "checkout"), ("tag",))
    if isinstance(found, str):
        return found
    if found["commit"] != install.name:
        return f"manifest names commit {found['commit']}"
    if not files.runnable(python_of(install)):
        return f"{python_of(install)} is not an executable file"
    return Manifest(found["commit"], found.get("tag"), found["installed_at"], found["checkout"])


NOT_AN_INSTALL: Final = {"dangling": "is a link to nothing", "file": "is not a directory", "other": "is not a directory",
                         "unexaminable": "cannot be examined"}
NOT_A_MANIFEST: Final = {"dangling": "is a link to nothing", "directory": "is not a file", "other": "is not a file",
                         "unexaminable": "cannot be examined"}


def state(files: Reads, root: Path, commit: str) -> State:
    """The one validity rule: absent with nothing at `installs/<commit>`; incomplete for a directory with no manifest;
    complete when the manifest is valid (`_valid`); broken for anything else there (a file, a link to nothing, a path that
    cannot be examined, an invalid or unreadable manifest). Takes no lock: the manifest is the last, atomic write."""
    install = root / commit
    if not is_commit(commit):
        return State("absent")
    found_install, manifest = files.kind(install), install / MANIFEST
    if found_install != "directory":
        return State("absent") if found_install == "absent" else State("broken", detail=f"{install} {NOT_AN_INSTALL[found_install]}")
    found_manifest = files.kind(manifest)
    if found_manifest == "absent":
        return State("incomplete")
    if found_manifest != "file":
        return State("broken", detail=f"{manifest} {NOT_A_MANIFEST[found_manifest]}")
    try:
        text = files.read_text(manifest)
    except (OSError, UnicodeError) as error:
        return State("broken", detail=f"manifest unreadable: {type(error).__name__}")
    valid = _valid(files, install, text)
    return State("broken", detail=valid) if isinstance(valid, str) else State("complete", valid)
