"""The installed releases of the two plugins: <claude dir>/plugins/cache/<marketplace>/<plugin>/<version>, and the version Claude Code
records as installed."""
import json
from pathlib import Path
from typing import Final

from taskloop.contracts.ids import Version

PLUGINS: Final = {"task-loop": ("iorlas-task-loop", "skills/task-loop/tl.py"), "delegate": ("iorlas-delegate", "skills/delegate/route.py")}


def version_tuple(name: str) -> tuple[int, ...] | None:
    try:
        return tuple(Version.parse(name))
    except ValueError:
        return None


def cache_dirs(key: str, claude: Path) -> dict[str, Path]:
    """{version: dir} of the installed cache dirs of plugin `key` ("task-loop" | "delegate") that hold the plugin's main file. Half-copied
    dirs and non-version names are left out."""
    plugin, mark = PLUGINS[key]
    out: dict[str, Path] = {}
    for d in sorted((claude / "plugins" / "cache").glob(f"*/{plugin}/*")):
        if version_tuple(d.name) and (d / mark).is_file():
            out.setdefault(d.name, d)
    return out


def installed_version(key: str, claude: Path) -> str:
    """The version in installed_plugins.json (user scope) for plugin `key`, else ""."""
    plugin = PLUGINS[key][0]
    try:
        recs = json.loads((claude / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))["plugins"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    for name, entries in recs.items():
        if name.split("@")[0] == plugin and isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("scope") == "user":
                    return Path(str(e.get("installPath") or "")).name
    return ""


def releases_behind(version: str, claude: Path, key: str = "task-loop") -> int:
    """How many installed releases of plugin `key` are newer than `version` (0 when it is the newest or unknown)."""
    mine = version_tuple(version)
    return sum(1 for v in cache_dirs(key, claude) if mine and (version_tuple(v) or ()) > mine)


def previous_version(key: str, current: str, claude: Path) -> str:
    cur = version_tuple(current) or ()
    below = [v for v in cache_dirs(key, claude) if (version_tuple(v) or ()) < cur]
    return max(below, key=lambda v: version_tuple(v) or ()) if below else ""
