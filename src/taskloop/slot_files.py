"""The slot file port over the real file system. Wired by `composition`."""

import os
import stat
from pathlib import Path

from taskloop.attempt_types import FileStat


class RealSlotFiles:
    """The slot file port over the real file system: `lstat` never follows a symlink, and a read opens only what `lstat`
    just saw as a regular file within the cap (`O_NOFOLLOW`, non-blocking), so a FIFO or symlink is never opened."""

    def lstat(self, path: Path) -> FileStat | None:
        try:
            found = os.lstat(path)
        except (OSError, ValueError):  # ValueError: an embedded NUL; fails closed like a missing file
            return None
        mode = found.st_mode
        if stat.S_ISREG(mode):
            return FileStat("file", found.st_size, bool(mode & 0o111))
        return FileStat("dir" if stat.S_ISDIR(mode) else "link" if stat.S_ISLNK(mode) else "other", found.st_size, False)

    def read(self, path: Path, cap: int) -> bytes | None:
        entry = self.lstat(path)
        if entry is None or entry.kind != "file" or entry.size > cap:
            return None
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except (OSError, ValueError):
            return None
        with os.fdopen(descriptor, "rb") as stream:
            data = stream.read(cap + 1)
        return data if len(data) <= cap else None

    def resolve(self, path: Path) -> Path | None:
        try:
            return path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return None
