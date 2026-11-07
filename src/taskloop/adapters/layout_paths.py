"""Paths owned by taskloop.adapters."""
from pathlib import Path

from tlkernel.paths import ConfigDir


def layout_journal(cfg: ConfigDir) -> Path:
    """What `tl layout migrate` moved, one line per move."""
    return cfg.root / "layout-migrate.jsonl"


def retired_dir(cfg: ConfigDir) -> Path:
    """retired/: what `tl layout migrate` set aside because no registered repo owns it (an old repo key it cannot map)."""
    return cfg.root / "retired"
