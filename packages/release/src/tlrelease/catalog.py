"""Installed task-loop releases and the version Claude Code records as installed."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

import any_plugin_cache as apc
from tlkernel.paths import ConfigDir

from tlrelease import pins
from tlrelease.versions import Installs

PLUGIN: Final = "iorlas-task-loop"

version_tuple = apc.version_key


def cache_dirs(claude: Path) -> dict[str, Path]:
    """{version: dir} of installed task-loop cache dirs that hold the main file."""
    return apc.installs(claude, PLUGIN, "skills/task-loop/tl.py")


def installed_version(claude: Path) -> str:
    return apc.installed_version(claude, PLUGIN)


def releases_behind(version: str, claude: Path) -> int:
    return apc.behind(cache_dirs(claude), version)


def previous_version(current: str, claude: Path) -> str:
    return apc.previous(cache_dirs(claude), current)


def installs(cfg: ConfigDir, root: Path, claude_dir: Callable[[], Path], now: Callable[[], float] = time.time) -> Installs:
    """The machine's installs, with the owner's standing pin taking precedence."""
    return Installs(cfg, root, lambda: installed_version(claude_dir()), lambda: pins.read_pin(cfg).task_loop or "", now=now)


def installed_newer(cfg: ConfigDir, root: Path, claude_dir: Callable[[], Path], now: Callable[[], float]) -> tuple[str, Path] | None:
    """The install selected at a running engine's step boundary."""
    found = installs(cfg, root, claude_dir, now).move_to()
    return (found.version, found.dir) if found else None
