"""Age retention for trace logs, preserving land evidence and undecodable lines."""

import json
import math

from tlkernel.guard import guard
from tlkernel.paths import ConfigDir
from tlkernel.stores import TraceStore


def _old(line: str, cutoff: float, keep_beads: frozenset[str]) -> bool:
    try:
        row = json.loads(line)
        if not isinstance(row, dict):
            return False
        ended = row.get("ended")
        protected = (row.get("outcome") in ("LANDED", "landed") or row.get("event") in ("LANDED", "landed")
                     or row.get("bead") in keep_beads)
        return (not protected and isinstance(ended, (int, float)) and not isinstance(ended, bool)
                and math.isfinite(ended) and ended < cutoff)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False


def prune_traces(cfg: ConfigDir, days: float, now: float, dry_run: bool,
                 keep_beads: frozenset[str] = frozenset()) -> int:
    """Remove rows with ended before the cutoff under the append lock; dry runs only count.

    Malformed lines, missing/invalid times, exempt beads and all LANDED rows
    survive. Preserve retained lines verbatim, including incomplete last lines.
    """
    path, cut = cfg.traces(), now - days * 86400
    if not path.exists():
        return 0
    store = TraceStore(cfg)
    if not dry_run:
        return store.file.rewrite(lambda line: not _old(line.decode("utf-8", "replace"), cut, keep_beads))
    with guard(store.lock_path()):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, UnicodeError):
            return 0
    return sum(1 for line in lines if _old(line, cut, keep_beads))
