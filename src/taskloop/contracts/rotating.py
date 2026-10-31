"""RotatingJsonl: the one writer of every JsonlStore file. Before a line would take the file past `rotate_bytes` the files shift
(`.1` ... `.{keep-1}`, the oldest dropped), so a store is bounded by rotate_bytes x keep. Reads (cursor, tail) are the Jsonl ones, over
the current file: a cursor past the end of a freshly rotated file reads from 0."""
import json
from pathlib import Path
from typing import override

from jsonl_log import KEEP, ROTATE_BYTES, Jsonl, JsonlLog


class RotatingJsonl(Jsonl):
    def __init__(self, path: Path, rotate_bytes: int = ROTATE_BYTES, keep: int = KEEP) -> None:
        super().__init__(path)
        self.log = JsonlLog(path, rotate_bytes=rotate_bytes, keep=keep)

    @override
    def append(self, data: dict[str, object]) -> int:
        """Write one line; -> the offset of its first byte in the current file."""
        at = self.log.append_at((json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
        assert at is not None  # the log is never read-only here
        return at
