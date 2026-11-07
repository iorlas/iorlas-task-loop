"""Installed task-loop releases and the version Claude Code records as installed."""

from pathlib import Path
from typing import Final

import any_plugin_cache as apc

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
