"""The reader of one attempt's `events.jsonl`: the agent's activity, one `any_agent.activity` record per line, written while the
attempt runs by `command_sink`. Display only, never control state. Each file read takes at most READ_CAP bytes; timestamp searches
also obey the owning stream cap. A page carries an
opaque cursor (the file's identity and the byte after the last whole line read) to follow with; a cursor that does not belong to
the file, or is past its end, answers `replaced` with the fresh tail instead of repeating or skipping lines."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from any_agent.activity import Activity, decode

READ_CAP = 256 << 10  # bytes one read takes from the file


@dataclass(frozen=True)
class ActivityPage:
    events: tuple[Activity, ...]  # a command or tool is its latest record only; oldest first
    cursor: str  # hand it back to `follow`; START when the file does not exist yet
    replaced: bool = False  # the cursor was not this file's: `events` are its fresh tail
    available: bool = True  # False: no events file (an attempt from before it, or one that never ran an agent)


START = "0:0"  # a cursor for a file that is not there yet: it follows from the first byte of whatever file appears
GONE = ActivityPage((), START, available=False)


def _collapse(records: list[Activity]) -> tuple[Activity, ...]:
    """A running record is replaced, in its place, by the finished record of its id."""
    found: dict[str, Activity] = {}
    for record in records:
        found[record.id or f"#{len(found)}"] = record
    return tuple(found.values())


def _lines(chunk: bytes, start: int) -> tuple[list[Activity], int]:
    """The records of the whole lines of `chunk` and the offset after the last whole line (a half-written line waits)."""
    whole = chunk[: chunk.rfind(b"\n") + 1]
    return [record for line in whole.splitlines() if (record := _record(line)) is not None], start + len(whole)


def _record(line: bytes) -> Activity | None:
    try:
        return decode(line.decode("utf-8", "replace"))
    except (ValueError, OverflowError):  # display-only data: a line that cannot be read is skipped
        return None


def _cursor(inode: int, offset: int) -> str:
    return f"{inode}:{offset}"


def _read(stream: BinaryIO, start: int, end: int) -> bytes:
    stream.seek(start)
    return stream.read(end - start)


def _command_start(line: bytes) -> float | Literal["unreadable"] | None:
    try:
        record = decode(line.decode("utf-8"))
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        return "unreadable"
    if record is None:
        return "unreadable"
    return record.at if record.kind == "command" and record.state == "running" else None


def _command_time(stream: BinaryIO, size: int, truncated: bytes) -> float | Literal["none", "unreadable"]:
    """Search complete records newest first, retaining at most READ_CAP bytes of a split line."""
    end, pending, final = size, b"", True
    marker = truncated.removesuffix(b"\n")
    while end:
        room = READ_CAP - len(pending)
        if room <= 0:
            return "unreadable"
        start = max(0, end - room)
        chunk = _read(stream, start, end)
        if len(chunk) != end - start:
            return "unreadable"
        lines = (chunk + pending).split(b"\n")
        pending = lines[0]
        for line in reversed(lines[1:]):
            if final:  # an unterminated append is not yet a record, even when it happens to decode
                final = False
                if line.endswith(marker):
                    return "unreadable"
                continue
            found = _command_start(line)
            if found is not None:
                return found
        if final and pending.endswith(marker):
            return "unreadable"
        end = start
    found = None if final else _command_start(pending)  # no complete record in an empty or wholly unfinished file
    return "none" if found is None else found


def command_time(path: Path, cap: int, truncated: bytes) -> float | Literal["none", "unreadable"]:
    """The last appended command start, from a bounded snapshot; neither completions nor dashboard folding apply."""
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if size > cap + len(truncated):
                return "unreadable"
            return _command_time(stream, size, truncated)
    except FileNotFoundError:
        return "none"
    except OSError:
        return "unreadable"


def _tail(stream: BinaryIO, inode: int, size: int, limit: int, replaced: bool) -> ActivityPage:
    start = max(0, size - READ_CAP)
    chunk = _read(stream, start, size)
    if start:
        chunk = chunk[chunk.find(b"\n") + 1 :]  # the cut first line
        start = size - len(chunk)
    records, end = _lines(chunk, start)
    return ActivityPage(_collapse(records)[-limit:], _cursor(inode, end), replaced)


def _parsed(cursor: str) -> tuple[int, int] | None:
    inode, _, offset = cursor.partition(":")
    return (int(inode), int(offset)) if inode.isdigit() and offset.isdigit() else None


def tail(path: Path, limit: int) -> ActivityPage:
    """The latest `limit` actions, from a bounded read of the end of the file; GONE when it cannot be opened."""
    try:
        with path.open("rb") as stream:
            status = os.fstat(stream.fileno())
            return _tail(stream, status.st_ino, status.st_size, limit, False)
    except OSError:
        return GONE


def follow(path: Path, cursor: str, limit: int) -> ActivityPage:
    """What was appended after `cursor` (at most READ_CAP bytes; the next page continues), or `replaced` with the tail of `limit`."""
    try:
        with path.open("rb") as stream:
            status = os.fstat(stream.fileno())
            at = _parsed(cursor)
            if at == (0, 0):
                at = (status.st_ino, 0)
            if at is None or at[0] != status.st_ino or at[1] > status.st_size:
                return _tail(stream, status.st_ino, status.st_size, limit, True)
            chunk = _read(stream, at[1], min(status.st_size, at[1] + READ_CAP))
            records, end = _lines(chunk, at[1])
            if end == at[1] and len(chunk) >= READ_CAP:  # one line longer than a read: skip the window, or the cursor never moves
                end += len(chunk)
            return ActivityPage(_collapse(records), _cursor(status.st_ino, end))
    except OSError:
        return GONE
