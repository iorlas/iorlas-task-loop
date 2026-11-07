"""RotatingJsonl: the one writer of every JsonlStore file. Before a line would take the file past `rotate_bytes` the files shift
(`.1` ... `.{keep-1}`, the oldest dropped), so a store is bounded by rotate_bytes x keep. Reads (cursor, tail) are the Jsonl ones, over
the current file: a cursor past the end of a freshly rotated file reads from 0."""
import json
import sys
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import override

from jsonl_log import KEEP, ROTATE_BYTES, Jsonl, JsonlLog

NO_ROTATION = sys.maxsize  # rotate_bytes of a log that is pruned by age (rewrite) and never shifted into .1 files


class RotatingJsonl(Jsonl):
    def __init__(self, path: Path, rotate_bytes: int = ROTATE_BYTES, keep: int = KEEP, rotate_lock: Path | bool = False) -> None:
        super().__init__(path)
        self.log = JsonlLog(path, rotate_bytes=rotate_bytes, keep=keep, rotate_lock=rotate_lock)
        # the log holds its append descriptor open until closed: a store dropped without a close would keep it for the life of the process
        weakref.finalize(self, self.log.close)

    def rewrite(self, keep: Callable[[bytes], bool]) -> int:
        """Keep the lines `keep` accepts, under the rotate lock; -> how many lines went."""
        return self.log.rewrite(keep)

    @override
    def append(self, data: dict[str, object]) -> int:
        """Write one line; -> the offset of its first byte in the current file."""
        at = self.log.append_at((json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
        assert at is not None  # the log is never read-only here
        return at
