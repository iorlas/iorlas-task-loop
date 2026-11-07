"""Paths owned by tlrelease."""
from pathlib import Path

from tlkernel.paths import ConfigDir


def releases_dir(cfg: ConfigDir) -> Path:
    return cfg.root / "releases"
