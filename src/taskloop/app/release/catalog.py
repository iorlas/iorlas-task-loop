"""The installed release of the plugin: <claude dir>/plugins/cache/<marketplace>/<plugin>/<version>, and the version Claude Code
records as installed. The reading is any_plugin_cache's; this names the plugin."""

from pathlib import Path
from typing import Final

import any_plugin_cache as apc

PLUGINS: Final = {"task-loop": ("iorlas-task-loop", "skills/task-loop/tl.py")}

version_tuple = apc.version_key


def cache_dirs(key: str, claude: Path) -> dict[str, Path]:
    """{version: dir} of the installed cache dirs of plugin `key` ("task-loop") that hold the plugin's main file."""
    plugin, mark = PLUGINS[key]
    return apc.installs(claude, plugin, mark)


def installed_version(key: str, claude: Path) -> str:
    return apc.installed_version(claude, PLUGINS[key][0])


def releases_behind(version: str, claude: Path, key: str = "task-loop") -> int:
    return apc.behind(cache_dirs(key, claude), version)


def previous_version(key: str, current: str, claude: Path) -> str:
    return apc.previous(cache_dirs(key, claude), current)
