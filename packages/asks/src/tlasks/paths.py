"""Paths owned by tlasks."""
from pathlib import Path

from tlkernel.paths import ConfigDir


def ask_marker(cfg: ConfigDir, sweep: str) -> Path:
    """When a throttled sweep of the asks last ran (the file's mtime); not an ask, so the store never lists it."""
    return cfg.root / "asks" / ("." + sweep)
