"""Paths owned by tlland."""
from pathlib import Path

from tlkernel.paths import ConfigDir


def land_push(cfg: ConfigDir, stamp: int, branch: str) -> Path:
    return cfg.root / "land-push" / f"{stamp}-{branch}.log"


def push_log(run_dir: Path | str, stamp: int) -> Path:
    return Path(run_dir) / "land-push" / f"{stamp}.log"
