"""Bounded, display-only pages of check evidence. Outcomes come from the caller, never the log text."""

import base64
import binascii
import os
import re
from collections import deque
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from taskloop.command_conclusion import CommandConclusion

READ_CAP = 256 << 10
LINE_CAP = 8192
EVENT_CAP = 20
CURSOR_CAP = 256 << 10
INTEGER_CAP = (1 << 64) - 1


class CheckState(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    UNFINISHED = "unfinished"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CheckLog(Model):
    position: int = Field(ge=0, le=INTEGER_CAP)
    name: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")
    state: CheckState
    conclusion: CommandConclusion | None = None


class Offset(Model):
    log: CheckLog
    device: int = Field(default=0, ge=0, le=INTEGER_CAP)
    inode: int = Field(default=0, ge=0, le=INTEGER_CAP)
    offset: int = Field(default=0, ge=0, le=INTEGER_CAP)
    state: CheckState | None = None
    conclusion: CommandConclusion | None = None


class CheckCursor(Model):
    attempt: str = Field(min_length=1, max_length=256)
    block: int = Field(ge=0, le=INTEGER_CAP)
    logs: tuple[Offset, ...] = Field(max_length=1024)


class Record(Model):
    block: int
    position: int
    name: str
    offset: int | None = None  # None identifies a lifecycle summary
    end: int | None = None
    text: str | None = None
    state: CheckState
    conclusion: CommandConclusion | None = None


class CheckPage(Model):
    records: tuple[Record, ...]
    cursor: str
    available: bool
    replaced: bool


def encode(cursor: CheckCursor) -> str:
    return base64.urlsafe_b64encode(cursor.model_dump_json().encode()).rstrip(b"=").decode("ascii")


def decode(cursor: str) -> CheckCursor:
    """One URL-safe codec shared by the HTTP edge and the evidence reader; no paths are accepted."""
    if len(cursor) > CURSOR_CAP or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
        raise ValueError("Invalid check cursor")
    try:
        data = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        found = CheckCursor.model_validate_json(data)
        if len({each.log.position for each in found.logs}) != len(found.logs) or encode(found) != cursor:
            raise ValueError("Invalid check cursor")
    except (binascii.Error, ValueError) as error:
        raise ValueError("Invalid check cursor") from error
    return found


def _status(path: Path | None) -> os.stat_result | None:
    if path is None:
        return None
    try:
        return path.stat()
    except OSError:
        return None


def _changed(previous: Offset, status: os.stat_result | None) -> bool:
    return (
        status is not None
        and previous.inode != 0
        and ((previous.device, previous.inode) != (status.st_dev, status.st_ino) or previous.offset > status.st_size)
    )


def _records(data: bytes, start: int, log: CheckLog, block: int, final: bool, tail: bool) -> tuple[list[Record], int]:
    records: deque[Record] = deque(maxlen=EVENT_CAP)
    offset = 0
    while offset < len(data):
        newline = data.find(b"\n", offset, offset + LINE_CAP)
        length = newline + 1 - offset if newline >= 0 else min(LINE_CAP, len(data) - offset)
        if newline < 0 and length < LINE_CAP and not final:
            break
        records.append(
            Record(
                block=block,
                position=log.position,
                name=log.name,
                offset=start + offset,
                end=start + offset + length,
                text=data[offset : offset + length].decode("utf-8", "replace"),
                state=log.state,
                conclusion=log.conclusion,
            )
        )
        offset += length
        if not tail and len(records) == EVENT_CAP:
            break
    return list(records), start + offset


def _read(path: Path | None, previous: Offset, block: int, budget: int, tail: bool) -> tuple[list[Record], Offset, int, bool]:
    log = previous.log
    if path is None:
        return [], previous, 0, False
    try:
        with path.open("rb") as stream:
            status = os.fstat(stream.fileno())
            start = max(0, status.st_size - budget) if tail else previous.offset
            stream.seek(start)
            data = stream.read(budget)
    except OSError:
        return [], previous, 0, False
    records, end = _records(data, start, log, block, log.state != CheckState.RUNNING and start + len(data) >= status.st_size, tail)
    current = previous.model_copy(update={"device": status.st_dev, "inode": status.st_ino, "offset": end})
    return records, current, len(data), True


def _summary(log: CheckLog, block: int) -> Record:
    return Record(block=block, position=log.position, name=log.name, state=log.state, conclusion=log.conclusion)


def read(attempt: str, block: int, logs: tuple[tuple[CheckLog, Path | None], ...], cursor: str | None) -> CheckPage:
    """Tail the latest block, or follow every unconsumed byte in check-position order, sharing one read budget."""
    prior = decode(cursor) if cursor is not None else None
    old = {each.log.position: each for each in prior.logs} if prior is not None else {}
    replaced = prior is not None and (prior.attempt != attempt or prior.block != block)
    for log, path in logs:
        previous = old.get(log.position)
        if previous is not None and (previous.log.name != log.name or _changed(previous, _status(path))):
            replaced = True
    tail = prior is None or replaced
    offsets = {
        log.position: Offset(log=log) if tail or log.position not in old else old[log.position].model_copy(update={"log": log})
        for log, _path in logs
    }
    records: deque[Record] = deque(maxlen=EVENT_CAP)
    budget, available = READ_CAP, bool(logs)
    for log, path in reversed(logs) if tail else logs:
        previous = offsets[log.position]
        if not tail and len(records) == EVENT_CAP:
            break
        found, current, used, readable = _read(path, previous, block, budget, tail)
        budget -= used
        available = available and readable
        if not tail:
            found = found[: EVENT_CAP - len(records)]
            if found and found[-1].end is not None:
                current = current.model_copy(update={"offset": found[-1].end})
        emitted = list(found)
        changed = (previous.state, previous.conclusion) != (log.state, log.conclusion)
        if changed and (tail or len(records) + len(emitted) < EVENT_CAP):
            emitted.append(_summary(log, block))
            current = current.model_copy(update={"state": log.state, "conclusion": log.conclusion})
        if tail:
            records = deque((emitted + list(records))[-EVENT_CAP:], maxlen=EVENT_CAP)
        else:
            records.extend(emitted)
        offsets[log.position] = current
    next_cursor = CheckCursor(attempt=attempt, block=block, logs=tuple(offsets[log.position] for log, _path in logs))
    return CheckPage(records=tuple(records), cursor=encode(next_cursor), available=available, replaced=replaced)
