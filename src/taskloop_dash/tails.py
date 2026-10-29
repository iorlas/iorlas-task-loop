"""Reading the end of a big JSON-lines file without loading it, and the small JSON helpers every reader shares."""

import json
from datetime import datetime
from typing import Any

TAIL_BYTES = 6_000_000  # never read more than this from the end of a transcript


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
    def __init__(self, tail_bytes: int = TAIL_BYTES) -> None:
        self.tail_bytes = tail_bytes

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

