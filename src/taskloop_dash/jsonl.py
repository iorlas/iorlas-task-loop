"""JSON-lines files read the way the dashboard needs them: a whole file as typed records, or only what is new after a byte offset.
A line that is not a record is skipped; a half-written last line waits for the next read."""

import json
import os
from collections.abc import Callable
from typing import Any

from taskloop.contracts import log
from taskloop.contracts.codec import CodecError

CHUNK = 1 << 20  # bytes read from one file per call; a long backlog arrives over several polls


def parse(raw: bytes | str, decode: Callable[[object], Any] = log.decode) -> Any:
    """The typed record of one line, None when it is not one."""
    try:
        return decode(json.loads(raw))
    except (ValueError, CodecError):
        return None


def records(path: str, decode: Callable[[object], Any] = log.decode) -> list[Any]:
    """Every record of the file, oldest first."""
    try:
        with open(path, "rb") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    return [r for r in (parse(ln, decode) for ln in lines) if r is not None]


def read_from(path: str, offset: int, decode: Callable[[object], Any] = log.decode) -> tuple[list[tuple[int, Any]], int]:
    """([(offset of the line, record)] of the complete lines after `offset`, the offset to ask next). A file that shrank starts over."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], offset
    if size < offset:
        offset = 0
    if size == offset:
        return [], offset
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(CHUNK)
    end = data.rfind(b"\n")
    if end < 0:
        return [], offset
    out: list[tuple[int, Any]] = []
    pos = offset
    for raw in data[: end + 1].split(b"\n")[:-1]:
        rec = parse(raw, decode)
        if rec is not None:
            out.append((pos, rec))
        pos += len(raw) + 1
    return out, offset + end + 1


def size_of(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
