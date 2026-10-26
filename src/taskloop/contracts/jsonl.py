"""Append-only JSON Lines with byte offsets that never move.

An entry's `start` is the byte offset of its line; `end` is the offset after its newline, and the cursor a reader keeps. A last
line without its newline is still being written: it is not returned and the cursor stays at its start, so the next read
returns it whole. A complete line that is not a JSON object is skipped (the cursor passes it). One writer appends a line with
one write call, so a reader never sees half of a line except at the tail.
"""
import dataclasses
import json
import os
from pathlib import Path
from typing import Any

CHUNK = 1 << 16


@dataclasses.dataclass(frozen=True)
class Entry:
    start: int
    end: int
    data: dict[str, Any]


class Jsonl:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, data: dict[str, Any]) -> int:
        """Write one line, flushed; returns the offset of its first byte."""
        line = (json.dumps(data, ensure_ascii=False, separators=(", ", ": ")) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
            return os.lseek(fd, 0, os.SEEK_CUR) - len(line)
        finally:
            os.close(fd)

    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def read_from(self, offset: int = 0, limit: int | None = None) -> tuple[list[Entry], int]:
        """(entries from `offset`, the cursor after them). `limit` caps the entries returned; the cursor then stops after the
        last one returned. An offset past the end of the file (it was truncated) reads from 0."""
        try:
            with open(self.path, "rb") as f:
                if offset > os.fstat(f.fileno()).st_size:
                    offset = 0
                f.seek(offset)
                raw = f.read()
        except OSError:
            return [], offset
        entries, cursor = _parse(raw, offset, limit)
        return entries, cursor

    def tail(self, n: int, before: int | None = None) -> list[Entry]:
        """The last `n` complete entries that end at or before `before` (default: the end of the file), oldest first."""
        end = self.size() if before is None else min(before, self.size())
        if n <= 0 or end == 0:
            return []
        lo = end
        raw = b""
        with open(self.path, "rb") as f:
            while lo > 0 and raw.count(b"\n") <= n:
                lo = max(0, lo - CHUNK)
                f.seek(lo)
                raw = f.read(end - lo)
        if lo > 0:  # the window starts inside a line: drop that partial line
            cut = raw.find(b"\n")
            lo, raw = lo + cut + 1, raw[cut + 1:]
        entries, _ = _parse(raw, lo, None)
        return entries[-n:]


def _parse(raw: bytes, base: int, limit: int | None) -> tuple[list[Entry], int]:
    entries: list[Entry] = []
    pos = 0
    while limit is None or len(entries) < limit:
        nl = raw.find(b"\n", pos)
        if nl < 0:
            break  # a torn line: it waits
        line = raw[pos:nl]
        data = _decode(line)
        if data is not None:
            entries.append(Entry(base + pos, base + nl + 1, data))
        pos = nl + 1
    return entries, base + pos


def _decode(line: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(line.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError is one
        return None
    return data if isinstance(data, dict) else None
