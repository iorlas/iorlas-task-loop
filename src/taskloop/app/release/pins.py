"""pinned.json ({"task-loop": "0.23.38", "delegate": "0.40.1"}, each key optional) is written by `tl pin` and `tl rollback` only: the
owner's override. The loop reads it, never writes it. A pin names a plugin cache dir that must exist."""
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from taskloop.adapters.ident import claude_dir, config_dir
from taskloop.app.release.catalog import PLUGINS, cache_dirs, installed_version, previous_version, version_tuple
from taskloop.contracts.paths import ConfigDir


def pin_file() -> Path:
    return ConfigDir(config_dir()).pin()


def read_pin() -> dict[str, Any]:
    try:
        pin = json.loads(pin_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return pin if isinstance(pin, dict) else {}


def write_pin(pin: dict[str, Any]) -> None:
    f = pin_file()
    tmp = f.with_name(f.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(pin, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def pinned_dir(key: str) -> Path | None:
    """The cache dir `pinned.json` names for plugin `key`, None when it pins no version of it. A pin whose dir is gone gives a path
    that does not exist (the caller refuses; no fallback to another version)."""
    v = read_pin().get(key)
    if not v:
        return None
    return cache_dirs(key).get(str(v)) or claude_dir() / "plugins" / "cache" / "-" / PLUGINS[key][0] / str(v)


def clear_pin() -> bool:
    """Remove the pin; True when there was one."""
    had = bool(read_pin())
    with contextlib.suppress(OSError):
        pin_file().unlink()
    return had


def set_pin(task_loop: str = "", delegate: str = "") -> tuple[dict[str, Any], str]:
    """(the pin now, "" or why it is refused): a version that is not installed is refused, never pinned."""
    want = {"task-loop": task_loop, "delegate": delegate}
    for key, v in want.items():
        if v and v not in cache_dirs(key):
            have = sorted(cache_dirs(key), key=lambda x: version_tuple(x) or ())
            return read_pin(), "refused: {} {} is not installed under {} (installed: {})".format(
                PLUGINS[key][0], v, claude_dir() / "plugins" / "cache", ", ".join(have) or "none")
    pin = read_pin()
    pin.update({k: v for k, v in want.items() if v})
    pin["pinned_at"] = time.time()
    write_pin(pin)
    return pin, ""


def rollback_target() -> tuple[str, str, str]:
    """(task-loop version to pin, delegate version to keep, why not): the newest install below the current one."""
    pin = read_pin()
    newest = max(cache_dirs("task-loop"), key=lambda v: version_tuple(v) or (), default="")
    cur = pin.get("task-loop") or installed_version("task-loop") or newest
    if not cur:
        return "", "", "refused: no task-loop install to roll back from"
    prev = previous_version("task-loop", cur)
    if not prev:
        return "", "", f"refused: no task-loop version older than {cur} is installed"
    keep = pin.get("delegate") or installed_version("delegate")
    return prev, keep if keep in cache_dirs("delegate") else "", ""


def run_pin(version: str | None, delegate: str | None, clear: bool) -> int:
    """`tl pin [VERSION] [--delegate V] [--clear]`: show, set or clear the pin."""
    if clear:
        if version or delegate:
            sys.exit("tl: pin --clear takes no version")
        print("PIN CLEARED" if clear_pin() else "no pin was set")
        return 0
    if not (version or delegate):
        pin = read_pin()
        print(json.dumps(pin) if pin else "no pin")
        return 0
    pin, why = set_pin(version or "", delegate or "")
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    print("PINNED " + " ".join(f"{k} {pin[k]}" for k in ("task-loop", "delegate") if k in pin))
    return 0


def run_rollback() -> int:
    """`tl rollback`: pin the previous task-loop version (the delegate stays as it is)."""
    prev, keep, why = rollback_target()
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    return run_pin(prev, keep, False)
