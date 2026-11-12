"""`tl pin REV` and `tl pin --clear`: the owner's one pin operation (tl-8bh9.8.3 sections 6.2 and 11).

REV is resolved only from installed manifests (no Git, no checkout): a full commit id opens `installs/<commit>/` by name;
a tag name reads the manifest of each install directory named by a full commit id (the only listing of the installs;
lock and temporary files are skipped by name). The install must be complete by `installs.state`, the same rule the
resolver uses. The pin file is written atomically through `pin_file`. Never opens factory.db (Q13: rolling back onto a
newer factory.db is refused by the older code's own `refused schema` at its first command), never checks for running
rounds (Q7: the person drains first), never takes a lock.
"""

import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from taskloop import pin_file
from taskloop.installs import MANIFEST, Manifest, Reads, Writes, installs_root, is_commit, is_tag, state
from taskloop.pin_file import Pin, PinInvalid


class Files(Reads, Writes, Protocol):
    """`installs.state`'s reads, the pin file's atomic write and removal, the installs listing and the config folder."""

    def names(self, folder: Path) -> tuple[str, ...]: ...  # none when the folder does not exist
    def make_folder(self, folder: Path) -> None: ...  # with its parents; nothing when it exists


type Was = Pin | PinInvalid | None


@dataclass(frozen=True)
class Pinned:
    pin: Pin
    path: Path
    was: Was  # the pin before this call
    already: bool  # the pin already named this commit: the file is unchanged
    back: Pin | None = None  # `was` when it still names a complete install: the way back to it


@dataclass(frozen=True)
class Cleared:
    path: Path
    was: Was  # None: there was no pin file
    back: Pin | None = None  # `was` when it still names a complete install: the way back to it


@dataclass(frozen=True)
class Refused:
    word: str  # `config`, `revision`, `not_installed`, `incomplete`, `broken`, `ambiguous`
    detail: str


@dataclass(frozen=True)
class Unavailable:
    word: str  # `write`, `read` (the installs folder cannot be listed)
    detail: str


def _path(config: str | None, home: Path) -> Path | Refused:
    path = pin_file.pin_path(config, home)
    return Refused("config", pin_file.nameless(config).detail) if path is None else path


def _loose_tag(files: Files, install: Path) -> str | None:
    """The `tag` a broken install's manifest still names, read without its validity rule; None when it names none."""
    try:
        table = tomllib.loads(files.read_text(install / MANIFEST))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None
    found = table.get("tag")
    return found if isinstance(found, str) else None


def _recording(files: Files, root: Path, tag: str) -> list[tuple[str, Manifest | None]]:
    """Every install directory whose manifest names `tag` exactly (case included): complete ones with their manifest,
    broken ones with None. An incomplete one has no manifest, so it names no tag. OSError when `root` cannot be listed."""
    found: list[tuple[str, Manifest | None]] = []
    for name in files.names(root):
        if not is_commit(name):
            continue
        named = state(files, root, name)
        if named.manifest is not None and named.manifest.tag == tag:
            found.append((name, named.manifest))
        elif named.word == "broken" and _loose_tag(files, root / name) == tag:
            found.append((name, None))
    return found


def _by_tag(files: Files, root: Path, tag: str) -> Manifest | Refused | Unavailable:
    """The one install whose manifest records `tag`, complete; two (a moved tag, either of them broken) are `ambiguous`,
    one broken is `broken`, none `not_installed`."""
    try:
        found = _recording(files, root, tag)
    except NotADirectoryError:
        return Refused("broken", f"{root} is not a directory")
    except OSError as error:
        return Unavailable("read", f"{root} cannot be listed: {error}")
    if len(found) > 1:
        listed = ", ".join(name if manifest is not None else f"{name} (broken)" for name, manifest in found)
        return Refused("ambiguous", f"tag {tag} is recorded by {len(found)} installs ({listed}); tl pin COMMIT")
    if not found:
        return Refused("not_installed", f"no install under {root} records tag {tag}; tl install {tag} --checkout PATH")
    name, manifest = found[0]
    return manifest if manifest is not None else _by_commit(files, root, name)


def _by_commit(files: Files, root: Path, commit: str) -> Manifest | Refused:
    found, install = state(files, root, commit), root / commit
    if found.manifest is not None:  # complete
        return found.manifest
    if found.word == "incomplete":
        return Refused("incomplete", f"{install} has no manifest (an install never finished, or is still building)")
    if found.word == "broken":
        return Refused("broken", f"{install} is broken ({found.detail}); move it aside and tl install {commit} --checkout PATH")
    return Refused("not_installed", f"{commit} is not installed under {root}; tl install {commit} --checkout PATH")


def chosen(files: Files, home: Path, rev: str) -> Manifest | Refused | Unavailable:
    """The complete install REV names: a full commit id by name, else a tag name among the manifests."""
    root = installs_root(home)
    if is_commit(rev):
        return _by_commit(files, root, rev)
    if is_tag(rev):
        return _by_tag(files, root, rev)
    return Refused("revision", f"{rev!r} is neither a full commit id nor a tag name")


def pin(files: Files, home: Path, config: str | None, rev: str, now: datetime) -> Pinned | Refused | Unavailable:
    """Pin the complete install REV names for the machine config in use; `already` when the pin names its commit."""
    path = _path(config, home)
    if isinstance(path, Refused):
        return path
    manifest = chosen(files, home, rev)
    if not isinstance(manifest, Manifest):
        return manifest
    was = pin_file.read(files, path)
    if isinstance(was, Pin) and was.commit == manifest.commit:
        return Pinned(was, path, was, already=True)
    try:
        files.make_folder(path.parent)
        written = pin_file.write(files, path, manifest.commit, manifest.tag, now)
    except OSError as error:
        return Unavailable("write", f"{path}: {error}; the pin is unchanged")
    return Pinned(written, path, was, already=False, back=_back(files, home, was))


def clear(files: Files, home: Path, config: str | None) -> Cleared | Refused | Unavailable:
    """Remove the pin file of the machine config in use; `was` None when there was none."""
    path = _path(config, home)
    if isinstance(path, Refused):
        return path
    was = pin_file.read(files, path)
    try:
        removed = pin_file.clear(files, path)
    except OSError as error:
        return Unavailable("write", f"{path}: {error}")
    return Cleared(path, was if removed else None, _back(files, home, was) if removed else None)


def _back(files: Files, home: Path, was: Was) -> Pin | None:
    """The earlier pin when `tl pin` could choose it again: it was valid and names a complete install."""
    if isinstance(was, Pin) and isinstance(_by_commit(files, installs_root(home), was.commit), Manifest):
        return was
    return None
