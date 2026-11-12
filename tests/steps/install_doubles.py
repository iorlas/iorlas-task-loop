"""Installs and pins made on a home under tmp_path, through the real writers; file ports that refuse one read or write."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from taskloop import pin_file
from taskloop.installs import MANIFEST, Kind, LocalFiles, Manifest, atomic_write, installs_root, manifest_text, python_of

A: Final = "3f2a9c4e1b07" + "a" * 28
B: Final = "9b1e07d2aa31" + "b" * 28
NOW: Final = datetime(2026, 11, 20, 10, 5, tzinfo=UTC)


def make_install(home: Path, commit: str, tag: str | None = None, *, manifest: str | None = None) -> Path:
    """`installs/<commit>/` with an executable `venv/bin/python` and the manifest the writer formats (or `manifest`)."""
    install = installs_root(home) / commit
    python = python_of(install)
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    text = manifest_text(Manifest(commit, tag, "2026-11-20T10:00:00Z", "/home/u/src/task-loop")) if manifest is None else manifest
    atomic_write(LocalFiles(), install / MANIFEST, text)
    return install


def make_pin(home: Path, commit: str, tag: str | None = None, config: str | None = None) -> Path:
    path = pin_file.pin_path(config, home)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    pin_file.write(LocalFiles(), path, commit, tag, NOW)
    return path


class Refusing(LocalFiles):
    """The local files, except that reading `unreadable` raises, `unexaminable` cannot be examined, and the named write
    step (`write`: after half the bytes; `replace`) raises OSError."""

    def __init__(self, unreadable: Path | None = None, failing: str = "", unexaminable: Path | None = None) -> None:
        self.unreadable = unreadable
        self.failing = failing
        self.unexaminable = unexaminable

    def read_text(self, path: Path) -> str:
        if path == self.unreadable:
            raise PermissionError(13, "Permission denied", str(path))
        return super().read_text(path)

    def kind(self, path: Path) -> Kind:
        return "unexaminable" if path == self.unexaminable else super().kind(path)

    def fill(self, descriptor: int, data: bytes) -> None:
        if self.failing == "write":
            super().fill(descriptor, data[: len(data) // 2])
            raise OSError(28, "No space left on device")
        super().fill(descriptor, data)

    def replace(self, source: Path, target: Path) -> None:
        if self.failing == "replace":
            raise OSError(5, "Input/output error", str(target))
        super().replace(source, target)
