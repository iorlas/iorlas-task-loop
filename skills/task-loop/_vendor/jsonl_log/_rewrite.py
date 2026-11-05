"""The one place a log file is replaced rather than appended to: keep the lines a predicate accepts."""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, BinaryIO

from atomic_io import atomic_write_bytes

from jsonl_log._append import append_line, open_append

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _filter(raw: bytes, keep: Callable[[bytes], bool]) -> tuple[int, bytes]:
    """(lines dropped, the bytes to keep) of ``raw``, which holds whole lines; a blank line goes uncounted."""
    dropped = 0
    out: list[bytes] = []
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        if keep(line):
            out.append(line + b"\n")
        else:
            dropped += 1
    return dropped, b"".join(out)


class _Puller:
    """Reads an open file forward, returning only whole lines; a torn last line waits for the next pull."""

    def __init__(self, f: BinaryIO) -> None:
        self._f = f
        self.offset = 0

    def pull(self, keep: Callable[[bytes], bool]) -> tuple[int, bytes, bytes]:
        """(dropped, kept bytes, the torn fragment after the last newline) of what was written since the last pull."""
        _ = self._f.seek(self.offset)
        raw = self._f.read()
        cut = raw.rfind(b"\n") + 1
        self.offset += cut
        dropped, kept = _filter(raw[:cut], keep)
        return dropped, kept, raw[cut:]


def _sync_dir(path: Path) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def rewrite_file(path: Path, keep: Callable[[bytes], bool], *, then: Callable[[], None]) -> int:
    """Replace ``path`` by its lines ``keep`` accepts, atomically and only if one goes; returns the lines dropped.

    The new file is fsynced, keeps the old file's mode, and its directory is fsynced after the replace,
    so a crash leaves the old log or the new one, never an empty one. Lines another process appended while
    this ran are carried over: before the replace, and after it from the old file (a writer still holding the
    old inode); the latter land after the lines already kept. A torn last line (a write still in flight, or
    one torn by the filesystem) is kept and closed with a newline. ``then`` runs right after the replace
    (the caller drops its descriptor to the old file).
    """
    try:
        old = path.open("rb")
    except FileNotFoundError:
        return 0
    with old:
        puller = _Puller(old)
        dropped, kept, torn = puller.pull(keep)
        if not dropped:
            return 0
        more, tail, torn = puller.pull(keep)  # appended while the filter ran
        dropped += more
        body = kept + tail + (torn + b"\n" if torn.strip() else b"")
        atomic_write_bytes(path, body, fsync=True, keep_mode=True)
        _sync_dir(path)
        then()
        puller.offset += len(torn)  # the fragment went into the new file whole
        more, late, torn = puller.pull(keep)  # written to the old inode in the replace window
        dropped += more
        if late:
            fd = open_append(path)
            try:
                _ = append_line(fd, late)
            finally:
                os.close(fd)
    return dropped
