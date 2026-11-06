"""The one retention table for the config folder's logs that no other prune owns: a file past its area's age goes, by mtime.
Run data, factory history and traces have their own (app/prune/runs.py); a loop's `log.jsonl` and `exits.jsonl` are evidence and stay,
and its `loop-<pid>.log` files are kept by count (app/loop/core.py)."""
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from taskloop.app.prune.runs import Gone, size_of
from taskloop.contracts.paths import ConfigDir


@dataclass(frozen=True)
class Area:
    name: str
    glob: str  # relative to the config folder
    days: float  # the least age a file of the area keeps; `keep_days` stretches it, never shortens it


RETENTION: Final = (
    Area("land-push logs", "land-push/*.log", 30),
    Area("loop death records", "repos/*/loop/died-*.json", 30),
)


def prune(cfg: ConfigDir, keep_days: float, now: float, dry_run: bool) -> list[Gone]:
    """Remove (name, with `dry_run`) the files of every area older than max(area age, keep_days). A file that cannot be removed stays."""
    gone: list[Gone] = []
    for area in RETENTION:
        cut = now - max(area.days, keep_days) * 86400
        for path in sorted(cfg.root.glob(area.glob)):
            try:
                if not path.is_file() or path.is_symlink() or path.stat().st_mtime >= cut:
                    continue
                size = size_of(path)
                if not dry_run:
                    path.unlink()
            except OSError:
                continue
            gone.append(Gone(Path(path), size))
    return gone
