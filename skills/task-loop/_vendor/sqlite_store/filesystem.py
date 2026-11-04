"""Conservative mount detection with per-process verdict caching."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _mount_path(value: str) -> Path:
    for escaped, plain in ((r"\040", " "), (r"\011", "\t"), (r"\012", "\n"), (r"\134", "\\")):
        value = value.replace(escaped, plain)
    return Path(value)


def _filesystem_type(resolved: Path) -> str:
    """Use the deepest Linux mount; other POSIX systems report unknown."""
    fstype = "unknown"
    if sys.platform.startswith("linux"):
        mounts: list[tuple[int, str]] = []
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) >= 3:
                mount = _mount_path(fields[1])
                if resolved.is_relative_to(mount):
                    mounts.append((len(mount.parts), fields[2]))
        if mounts:
            fstype = max(mounts, key=lambda item: item[0])[1]
    return fstype


def _unsafe_filesystem(path: Path) -> bool | None:
    try:
        fstype = _filesystem_type(path)
        unsafe = (
            any(parent.is_mount() for parent in (path, *path.parents) if parent != Path(parent.anchor))
            if fstype == "unknown"
            else fstype.lower().startswith(("nfs", "cifs", "fuse", "smb", "osxfuse", "macfuse"))
        )
    except (OSError, ValueError, RuntimeError):
        return None
    else:
        return unsafe


class _FilesystemCache:
    def __init__(self) -> None:
        self.verdicts: dict[Path, bool] = {}
        self.pid = os.getpid()

    def clear(self) -> None:
        self.verdicts.clear()
        self.pid = os.getpid()

    def allowed(self, parent: Path) -> bool:
        if self.pid != os.getpid():
            self.clear()
        if parent not in self.verdicts:
            verdict = _unsafe_filesystem(parent)
            if verdict is None:
                return False
            self.verdicts[parent] = verdict
        return not self.verdicts[parent]


_CACHE = _FilesystemCache()
os.register_at_fork(after_in_child=_CACHE.clear)


def clear_filesystem_cache() -> None:
    """Forget mount verdicts after mount changes or replacement of a probe."""
    _CACHE.clear()


def filesystem_allowed(parent: Path) -> bool:
    """Allow local storage; refuse network/FUSE mounts and detection failures.

    Pass a resolved parent. Unknown types are allowed only without mounted
    ancestors below root; a network-backed root cannot be detected portably.
    """
    return _CACHE.allowed(parent)
