"""An append-only JSON-lines log, rotated by size and age, read back newest file first or by byte cursor.

- **Writes.** One ``write`` call per line on an ``O_APPEND`` descriptor, no ``fsync``: lines from
  several processes never interleave, and another process rotating the file is noticed on the
  next append. The file is opened in append mode only.
- **Rotation.** Before an append would take the file past ``rotate_bytes``, the files shift
  (``.{keep-2}`` → ``.{keep-1}``, the oldest dropped, …, the file → ``.1``), so at most
  ``keep`` files exist. A line is never split across files. Without ``rotate_lock`` rotation is not
  coordinated between processes (two rotating at the same moment may drop a file); with it the
  shift runs under a :mod:`process_lock` lock and re-checks the size once held.
- **Atomicity.** One ``write`` on an ``O_APPEND`` descriptor is atomic against other writers on a
  local filesystem (APFS, ext4); NFS gives no such promise. Only a line up to ``PIPE_BUF`` is
  atomic by POSIX itself.
- **Rewrite.** :meth:`JsonlLog.rewrite` keeps the lines a predicate accepts, under the same lock.
- **Held handles.** A :class:`JsonlLog` keeps its descriptor open between appends; :func:`held` is a
  per-process, fork-aware, size-bounded cache of them, one per path.
- **Retention.** ``max_age`` (seconds) deletes a rotated file nobody wrote to for that long, at
  open, at each rotation and on :meth:`JsonlLog.prune`; :func:`expire` does the same for any files.
- **Cursor.** :mod:`jsonl_log.cursor` reads a file by byte offset, a torn last line waiting.
- **Reads.** A missing file reads empty; a blank line, or one the caller's ``decode``
  refuses with ``ValueError``, is skipped.

The log is codec-agnostic: it moves bytes lines; what a line means is the caller's.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Self, TypeVar

from jsonl_log._append import append_line, open_append
from jsonl_log._retention import expire
from jsonl_log._rewrite import rewrite_file
from jsonl_log.cursor import Entry, Jsonl, decode_object, read_from, tail

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_T = TypeVar("_T")

#: The default size a file may reach before the next append rotates it: 5 MiB.
ROTATE_BYTES = 5 * 1024 * 1024

#: The default number of files kept: the log and ``.1`` … ``.4``.
KEEP = 5

#: How long a rotation or rewrite waits for ``rotate_lock`` before :class:`process_lock.LockHeldError`.
LOCK_TIMEOUT = 30.0

_REAPPEND = 3


class JsonlLogError(Exception):
    """A refusal of the log."""


class LogClosedError(JsonlLogError):
    """An append to a log that was closed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"the log {path} is closed")


class LineLostError(JsonlLogError):
    """An append whose file a rewrite replaced under it on every attempt: the line may not be in the log."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"the line for {path} may be lost: the file was replaced under every append attempt")


class LineError(JsonlLogError):
    """A line that holds a newline before its end: it would become two lines."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"a line for {path} holds a newline before its end")


def read_lines(path: Path) -> Iterator[bytes]:
    """The non-blank lines of one file, without their newlines; a missing file has none."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return
    for line in raw.splitlines():
        if line.strip():
            yield line


def read(path: Path, decode: Callable[[bytes], _T]) -> Iterator[_T]:
    """Every line of one file that ``decode`` accepts; a line it refuses with ``ValueError`` is skipped."""
    for line in read_lines(path):
        with contextlib.suppress(ValueError):
            yield decode(line)


class JsonlLog:
    """One rotated JSON-lines log. Append-only at the application level.

    ``rotate_lock`` (``True`` for ``<path>.lock``, or a path; ``path`` may be a ``str``) makes rotation and :meth:`rewrite`
    exclusive across processes; an append never takes it.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        rotate_bytes: int = ROTATE_BYTES,
        keep: int = KEEP,
        read_only: bool = False,
        max_age: float | None = None,
        rotate_lock: bool | Path | str = False,
    ) -> None:
        if keep < 1:
            msg = f"keep must be at least 1, got {keep}"
            raise ValueError(msg)
        path = Path(path)
        self._path = path
        self._rotate_bytes = rotate_bytes
        self._keep = keep
        self._read_only = read_only
        self._max_age = max_age
        self._fd: int | None = None
        self._closed = False
        self._transient = False  # the held cache evicted this log: a reopened descriptor lasts one append
        self._mutex = threading.RLock()
        self._lock_path: Path | None = (
            path.with_name(path.name + ".lock") if rotate_lock is True else Path(rotate_lock) if rotate_lock else None
        )

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        rotate_bytes: int = ROTATE_BYTES,
        keep: int = KEEP,
        read_only: bool = False,
        max_age: float | None = None,
        rotate_lock: bool | Path | str = False,
    ) -> JsonlLog:
        """The log at ``path``, opened for appending unless ``read_only``.

        ``max_age`` seconds retains rotated files; ``rotate_lock`` serialises rotation and :meth:`rewrite` across processes.
        """
        log = cls(Path(path), rotate_bytes=rotate_bytes, keep=keep, read_only=read_only, max_age=max_age, rotate_lock=rotate_lock)
        if not read_only:
            _ = log._current_fd()
            _ = log.prune()
        return log

    @property
    def path(self) -> Path:
        return self._path

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._close_file()
        self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def append(self, line: bytes) -> bool:
        """Write one line in a single ``write`` call; ``False`` (nothing written) on a read-only log.

        A missing trailing newline is added. Raises :class:`LogClosedError` once closed and
        :class:`LineError` for a newline before the end.
        """
        return self.append_at(line) is not None

    def append_at(self, line: bytes) -> int | None:
        """:meth:`append`, returning the byte offset of the line in the current file; ``None`` on a read-only log.

        The offset is what :func:`jsonl_log.cursor.read_from` takes to read from this line on.
        """
        if self._closed:
            raise LogClosedError(self._path)
        if self._read_only:
            return None
        data = line if line.endswith(b"\n") else line + b"\n"
        if b"\n" in data[:-1]:
            raise LineError(self._path)
        with self._mutex:
            try:
                fd = self._current_fd()
                size = os.fstat(fd).st_size
                if size and size + len(data) > self._rotate_bytes:
                    self._rotate(len(data))
                    fd = self._current_fd()
                at = append_line(fd, data)
                for attempt in range(_REAPPEND + 1):
                    if os.fstat(fd).st_nlink:
                        return at
                    if attempt == _REAPPEND:
                        break
                    # A rewrite replaced the file under this descriptor: the line went to an unlinked inode
                    # (the rewrite may have carried it over too, so it can now be there twice).
                    self._close_file()
                    fd = self._current_fd()
                    at = append_line(fd, data)
                raise LineLostError(self._path)
            finally:
                if self._transient:
                    self._close_file()  # evicted from the held cache: never keep a descriptor nobody can release

    def append_json(self, value: object) -> bool:
        """:meth:`append` of ``value`` as compact JSON."""
        return self.append(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())

    def files(self) -> list[Path]:
        """Every file the log may hold, newest first: the log, then ``.1`` … ``.{keep-1}``."""
        return [self._path, *(self._rotated(n) for n in range(1, self._keep))]

    def records(self, decode: Callable[[bytes], _T]) -> Iterator[_T]:
        """:func:`read` over every file, newest file first, each file in written order."""
        for path in self.files():
            yield from read(path, decode)

    def _rotated(self, n: int) -> Path:
        return self._path.with_name(f"{self._path.name}.{n}")

    def prune(self, *, now: float | None = None) -> list[Path]:
        """Delete the rotated files not written to for ``max_age`` seconds; returns them. Nothing without ``max_age``."""
        if self._max_age is None:
            return []
        return expire((self._rotated(n) for n in range(1, self._keep)), self._max_age, now=now)

    def _current_fd(self) -> int:
        """The append descriptor, reopened when another process rotated the file away from under it."""
        if self._fd is not None:
            try:
                if self._path.stat().st_ino == os.fstat(self._fd).st_ino:
                    return self._fd
            except FileNotFoundError:
                pass
            self._close_file()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = open_append(self._path)
        return self._fd

    def _close_file(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def locked(self, *, timeout: float | None = LOCK_TIMEOUT) -> contextlib.AbstractContextManager[object]:
        """Hold ``rotate_lock`` (re-entrant): wrap appends in it where an append must not meet a :meth:`rewrite`. No-op without one."""
        if self._lock_path is None:
            return contextlib.nullcontext()
        from process_lock import ProcessLock  # noqa: PLC0415  imported only by a caller that opted in to the lock

        return ProcessLock.acquire(self._lock_path, timeout=timeout, label="jsonl-log")

    def rewrite(self, keep: Callable[[bytes], bool]) -> int:
        """Keep the lines of the log file that ``keep`` accepts; returns how many lines were dropped.

        ``keep`` gets each non-blank line without its newline. Needs ``rotate_lock``; runs under it,
        replaces the file atomically and only when a line goes. Lines appended meanwhile by a process
        that does not hold the lock are caught up before and after the replace; only an append
        descheduled mid-call for the whole replace can be lost: wrap such appends in :meth:`locked`
        to rule that out. A last line without its newline is another writer's torn line and is kept.
        """
        if self._lock_path is None:
            msg = "rewrite needs rotate_lock"
            raise JsonlLogError(msg)
        if self._closed:
            raise LogClosedError(self._path)
        if self._read_only:
            return 0
        with self._mutex, self.locked():
            return rewrite_file(self._path, keep, then=self._close_file)

    def release_fd(self) -> None:
        """Close the descriptor but not the log; what the held cache's eviction uses.

        The log is then transient: an append reopens the descriptor and closes it again before returning, so a
        thread still holding an evicted log never leaves a descriptor open that nothing would release.
        """
        with self._mutex:
            self._transient = True
            self._close_file()

    def _rotate(self, incoming: int = 0) -> None:
        with self.locked():
            self._close_file()
            if self._lock_path is not None:
                try:
                    size = self._path.stat().st_size
                except FileNotFoundError:
                    size = 0
                if not size or size + incoming <= self._rotate_bytes:
                    return  # another process rotated while this one waited
            self._shift()

    def _shift(self) -> None:
        if self._keep == 1:
            self._path.unlink(missing_ok=True)
        else:
            for n in range(self._keep - 1, 1, -1):
                with contextlib.suppress(FileNotFoundError):
                    self._rotated(n - 1).replace(self._rotated(n))
            with contextlib.suppress(FileNotFoundError):
                self._path.replace(self._rotated(1))
        _ = self.prune()


def held(path: Path | str, **options: object) -> JsonlLog:
    """The process's one open :class:`JsonlLog` for ``path`` (``options`` as :meth:`JsonlLog.open`, used on first sight)."""
    from jsonl_log._held import HELD  # noqa: PLC0415  the cache imports this module

    return HELD.get(path, options)


def close_held(path: Path | str | None = None) -> None:
    """Close the held log of ``path``, or every held log of this process."""
    from jsonl_log._held import HELD  # noqa: PLC0415

    HELD.close(path)


def held_count(path: Path | str | None = None) -> int:
    """Held logs this process owns: for ``path`` 0 or 1, without it all."""
    from jsonl_log._held import HELD  # noqa: PLC0415

    return HELD.count(path)


__all__ = [
    "KEEP",
    "LOCK_TIMEOUT",
    "ROTATE_BYTES",
    "Entry",
    "Jsonl",
    "JsonlLog",
    "JsonlLogError",
    "LineError",
    "LineLostError",
    "LogClosedError",
    "append_line",
    "close_held",
    "decode_object",
    "expire",
    "held",
    "held_count",
    "open_append",
    "read",
    "read_from",
    "read_lines",
    "tail",
]
