"""Reading the end or the middle of a big JSON-lines file without loading it, and the small JSON helpers every reader shares."""

import json
import os
from datetime import datetime
from typing import Any, BinaryIO

TAIL_BYTES = 6_000_000  # never read more than this from the end of a transcript
WINDOW_BYTES = 40_000_000  # the most window_lines reads from the middle of a huge transcript


def parse_ts(s: object) -> float | None:
    """Epoch seconds from a number or an ISO time; None for anything else."""
    if not s:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_json(path: object, default: Any = None) -> Any:
    try:
        with open(str(path), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def read_dict(path: object) -> dict[str, Any]:
    """The JSON object in the file, {} for a missing file or anything else."""
    got = read_json(path, {})
    return got if isinstance(got, dict) else {}


class Tails:
    def __init__(self, tail_bytes: int = TAIL_BYTES, window_bytes: int = WINDOW_BYTES) -> None:
        self.tail_bytes, self.window_bytes = tail_bytes, window_bytes

    def tail_lines(self, path: str, limit: int | None = None) -> list[str]:
        limit = limit or self.tail_bytes
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - limit))
                data = f.read()
        except OSError:
            return []
        lines = data.decode("utf-8", "replace").splitlines()
        return lines[1:] if size > limit else lines

    @staticmethod
    def _ts_at(f: BinaryIO, pos: int, size: int) -> tuple[float | None, int]:
        """(timestamp, offset of its line) of the first full line that starts at or after pos and has one; (None, size) past the end."""
        f.seek(pos)
        if pos:
            f.readline()  # the rest of the line pos is inside
        for _ in range(50):
            at = f.tell()
            ln = f.readline()
            if not ln:
                return None, size
            try:
                t = parse_ts(json.loads(ln).get("timestamp"))
            except (ValueError, AttributeError):
                continue
            if t:
                return t, at
        return None, size

    def window_lines(self, path: str, t0: float | None = None, t1: float | None = None) -> list[str]:
        """The lines of a transcript from t0 on. A small file or a window the tail already covers is the tail; otherwise (a task
        worked hours ago in a long session) the start of the window is found by bisecting the file on byte offsets, since a
        transcript's timestamps only grow, and read from there up to t1 (window_bytes at most)."""
        try:
            size = os.path.getsize(path)
        except OSError:
            return []
        if not t0 or size <= self.tail_bytes:
            return self.tail_lines(path)
        try:
            with open(path, "rb") as f:
                t, _ = self._ts_at(f, size - self.tail_bytes, size)
                if t is None or t <= t0 - 2:  # the tail starts before the window: it holds the window
                    return self.tail_lines(path)
                lo, hi = 0, size - self.tail_bytes  # the answer is in [lo, hi]: first line with ts >= t0 - 2
                while hi - lo > 65536:
                    mid = (lo + hi) // 2
                    t, _at = self._ts_at(f, mid, size)
                    if t is not None and t < t0 - 2:
                        lo = mid
                    else:
                        hi = mid
                lo = max(0, lo - 1_000_000)  # a resumed session may re-append older lines: start a little early
                if t1 is None and size - lo > self.window_bytes:
                    return self.tail_lines(path)  # a live window longer than the cap: the newest events
                f.seek(lo)
                if lo:
                    f.readline()
                data = self._read_window(f, t1)
                cut = len(data) >= self.window_bytes
                data = data[: self.window_bytes]
        except OSError:
            return []
        lines = data.decode("utf-8", "replace").splitlines()
        return lines[:-1] if cut and not data.endswith(b"\n") else lines

    def _read_window(self, f: BinaryIO, t1: float | None) -> bytes:
        data = b""
        while len(data) < self.window_bytes:  # chunks, so a short window never reads the whole cap
            chunk = f.read(1_000_000)
            if not chunk:
                break
            data += chunk
            if t1:
                last = data.rsplit(b"\n", 2)
                try:
                    if len(last) > 2 and (parse_ts(json.loads(last[-2]).get("timestamp")) or 0) > t1 + 2:
                        break
                except (ValueError, AttributeError):
                    pass
        return data
