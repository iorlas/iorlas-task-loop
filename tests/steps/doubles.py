"""Plain test doubles shared by the plan tests; fixtures stay in conftest.py."""

import os
from pathlib import Path

from git_porcelain import GitUnavailable
from git_porcelain.testing import FakeRepo, FakeWorktree

from taskloop.attempt_types import FileStat


class FakeSlotFiles:
    """The slot file port over the Git fake: each linked worktree it has seen listed keeps a valid pointer into the fake's
    common directory (with its `commondir` and `gitdir` back-pointer), and its files are the fake checkout's, regular and
    0644. `entries` and `contents` override any path: a rewritten pointer, a symlink, a FIFO, an executable file."""

    def __init__(self, repo: FakeRepo) -> None:
        self.repo, self.common = repo, repo.identity().common_dir
        self.known: dict[Path, FakeWorktree] = {}
        self.entries: dict[Path, FileStat | None] = {}
        self.contents: dict[Path, bytes] = {}
        self.resolved: dict[Path, Path | None] = {}

    @property
    def slots(self) -> tuple[FakeWorktree, ...]:
        try:
            listed = self.repo.worktrees()
        except GitUnavailable:
            listed = ()
        for info in listed:
            if not info.is_main:
                self.known.setdefault(info.path, self.repo.worktree(info.path))
        return tuple(self.known.values())

    def _gitdir(self, slot: FakeWorktree) -> Path:
        return self.common / "worktrees" / slot.path.name

    @staticmethod
    def _files(slot: FakeWorktree) -> dict[str, bytes]:
        try:
            return slot.state().files
        except GitUnavailable:  # a dropped checkout has no files
            return {}

    def _data(self, path: Path) -> bytes | None:
        if path in self.contents:
            return self.contents[path]
        for slot in self.slots:
            pointers = {
                slot.path / ".git": f"gitdir: {self._gitdir(slot)}\n".encode(),
                self._gitdir(slot) / "commondir": b"../..\n",
                self._gitdir(slot) / "gitdir": f"{slot.path / '.git'}\n".encode(),
            }
            if path in pointers:
                return pointers[path]
            if path.is_relative_to(slot.path) and path != slot.path:
                return self._files(slot).get(path.relative_to(slot.path).as_posix())
        return None

    def _folder(self, path: Path) -> bool:
        for slot in self.slots:
            if path in (slot.path, self._gitdir(slot)):
                return True
            if path.is_relative_to(slot.path):
                prefix = path.relative_to(slot.path).as_posix() + "/"
                return any(name.startswith(prefix) for name in self._files(slot))
        return False

    def lstat(self, path: Path) -> FileStat | None:
        if path in self.entries:
            return self.entries[path]
        data = self._data(path)
        if data is not None:
            return FileStat("file", len(data), False)
        return FileStat("dir", 0, False) if self._folder(path) else None

    def resolve(self, path: Path) -> Path | None:
        """No symlinks in the fake unless `resolved` names one; `..` folds as the operating system would."""
        return self.resolved.get(path, Path(os.path.normpath(path)))

    def read(self, path: Path, cap: int) -> bytes | None:
        entry = self.lstat(path)
        return None if entry is None or entry.kind != "file" or entry.size > cap else self._data(path)
