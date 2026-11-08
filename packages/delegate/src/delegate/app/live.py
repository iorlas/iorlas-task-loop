"""Read delegate's live worker streams without exposing their file layout to callers."""

import json
import os
from pathlib import Path

from delegate.contracts.json_types import Json
from delegate.contracts.live import LiveFile, LiveLine, LiveRead


def files(live_dir: str) -> list[LiveFile]:
    """List live files by name; a missing folder has no streams."""
    try:
        return [
            LiveFile(name=p.stem, mtime=p.stat().st_mtime)
            for p in sorted(Path(live_dir).glob("*.jsonl")) if p.is_file()
        ]
    except OSError:
        return []


def read(live_dir: str, name: str, cursor: int = 0, ident: int = 0) -> LiveRead:
    """Read at most 1 MiB, leaving an incomplete last line for the next poll."""
    previous_cursor = cursor
    try:
        with (Path(live_dir) / f"{name}.jsonl").open("rb") as stream:
            stat = os.fstat(stream.fileno())
            identity = hash((stat.st_dev, stat.st_ino)) or 1
            reset = (ident not in (0, identity)) or stat.st_size < cursor
            if reset:
                cursor = 0
            stream.seek(cursor)
            data = stream.read(1 << 20)
    except OSError:
        return LiveRead(lines=[], cursor=0, ident=0, reset=previous_cursor > 0 or ident != 0)
    end = data.rfind(b"\n")
    lines: list[LiveLine] = []
    pos = cursor
    if end >= 0:
        for raw in data[:end + 1].split(b"\n")[:-1]:
            try:
                event: Json = json.loads(raw)
            except ValueError:
                event = None
            if (
                isinstance(event, dict) and isinstance(event.get("t"), (int, float))
                and isinstance(event.get("kind"), str) and event["kind"]
            ):
                lines.append(LiveLine(offset=pos, event=event))
            pos += len(raw) + 1
    return LiveRead(lines=lines, cursor=pos, ident=identity, reset=reset)
