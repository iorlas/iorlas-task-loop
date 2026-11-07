"""Paths owned by tldash."""
from pathlib import Path

from tlkernel.paths import ConfigDir


def dash_pid(cfg: ConfigDir) -> Path:
    return cfg.root / "dash.pid"
