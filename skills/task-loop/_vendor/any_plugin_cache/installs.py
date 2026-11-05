"""What Claude Code has installed: <claude dir>/plugins/cache/<marketplace>/<plugin>/<version>/, and the version it records as active."""

from __future__ import annotations

import glob
import json
from pathlib import Path


def version_key(name: str) -> tuple[int, ...] | None:
    """A dotted version as an orderable tuple of ints ("0.23.56" > "0.9.1"); None when `name` is not a plain dotted-int version."""
    parts = name.split(".")
    if not name or not all(p.isascii() and p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def installs(claude_dir: Path, plugin: str, marker: str | tuple[str, ...]) -> dict[str, Path]:
    """{version: dir} of the cache dirs of `plugin` (any marketplace) that hold every file in `marker` (paths relative to the dir; pass
    the plugin's manifest and main file so a copy that wrote only one of them is not an install). Incomplete dirs and non-version
    names are left out; the same version in two marketplaces keeps the first by name."""
    marks = (marker,) if isinstance(marker, str) else marker
    out: dict[str, Path] = {}
    for d in sorted((claude_dir / "plugins" / "cache").glob(f"*/{glob.escape(plugin)}/*")):
        if version_key(d.name) and all((d / m).is_file() for m in marks):
            out.setdefault(d.name, d)
    return out


def installed_version(claude_dir: Path, plugin: str) -> str:
    """The version `installed_plugins.json` records for `plugin` at user scope, else "" (no file, unreadable, or no such entry)."""
    try:
        recs = json.loads((claude_dir / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))["plugins"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    for name, entries in recs.items():
        if name.split("@")[0] == plugin and isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("scope") == "user":
                    return Path(str(e.get("installPath") or "")).name
    return ""


def previous(found: dict[str, Path], current: str) -> str:
    """The newest installed version strictly below `current`, "" when there is none or `current` is not a dotted version."""
    cur = version_key(current)
    if cur is None:
        return ""
    below = [v for v in found if (version_key(v) or ()) < cur]
    return max(below, key=lambda v: version_key(v) or ()) if below else ""


def rollback_target(found: dict[str, Path], pinned: str = "", installed: str = "") -> tuple[str, str]:
    """(version to pin, "" or why not): the newest install below the current one, where current is `pinned`, else `installed`
    (see installed_version), else the newest install. A pin is valid when it is in `found`: use `version in found`."""
    cur = pinned or installed or max(found, key=lambda v: version_key(v) or (), default="")
    if not cur:
        return "", "no install to roll back from"
    prev = previous(found, cur)
    return (prev, "") if prev else ("", f"no version older than {cur} is installed")


def behind(found: dict[str, Path], version: str) -> int:
    """How many installed versions are newer than `version` (0 when it is the newest or not a version)."""
    mine = version_key(version)
    return sum(1 for v in found if mine and (version_key(v) or ()) > mine)
