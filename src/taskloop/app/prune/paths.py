"""Paths owned by taskloop.app.prune."""
from pathlib import Path

from tlkernel.paths import ConfigDir
from tlrelease.paths import releases_dir


def suite_logs(cfg: ConfigDir) -> list[Path]:
    """The saved full output of every red release suite (releases/suite-*.log); nothing sweeps them but `tl prune`."""
    return sorted(releases_dir(cfg).glob("suite-*.log"))
