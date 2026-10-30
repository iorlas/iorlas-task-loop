"""pinned.json ({"task-loop": "0.23.38", "delegate": "0.40.1"}, each key optional) is written by `tl pin` and `tl rollback` only: the
owner's override. The loop reads it, never writes it. A pin names a plugin cache dir that must exist."""
import json
import sys
import time
from pathlib import Path

from taskloop.adapters.ident import claude_dir, config_dir
from taskloop.app.release.catalog import PLUGINS, cache_dirs, installed_version, previous_version, version_tuple
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.snapshots import Pin
from taskloop.contracts.stores import PinStore


def pin_store() -> PinStore:
    return PinStore(ConfigDir(config_dir()))


def read_pin() -> Pin:
    """The pin (an empty one when there is none, or the file is not a Pin of this version)."""
    return pin_store().get() or Pin()


def pin_version(pin: Pin, key: str) -> str:
    return (pin.task_loop if key == "task-loop" else pin.delegate) or ""


def pinned_dir(key: str) -> Path | None:
    """The cache dir `pinned.json` names for plugin `key`, None when it pins no version of it. A pin whose dir is gone gives a path
    that does not exist (the caller refuses; no fallback to another version)."""
    v = pin_version(read_pin(), key)
    if not v:
        return None
    return cache_dirs(key).get(v) or claude_dir() / "plugins" / "cache" / "-" / PLUGINS[key][0] / v


def clear_pin() -> bool:
    """Remove the pin; True when there was one."""
    had = pin_store().get() is not None
    pin_store().delete()
    return had


def set_pin(task_loop: str = "", delegate: str = "") -> tuple[Pin, str]:
    """(the pin now, "" or why it is refused): a version that is not installed is refused, never pinned."""
    want = {"task-loop": task_loop, "delegate": delegate}
    for key, v in want.items():
        if v and v not in cache_dirs(key):
            have = sorted(cache_dirs(key), key=lambda x: version_tuple(x) or ())
            return read_pin(), "refused: {} {} is not installed under {} (installed: {})".format(
                PLUGINS[key][0], v, claude_dir() / "plugins" / "cache", ", ".join(have) or "none")
    old = read_pin()
    pin = old.replace(task_loop=task_loop or old.task_loop, delegate=delegate or old.delegate, pinned_at=time.time())
    pin_store().write(pin)
    return pin, ""


def rollback_target() -> tuple[str, str, str]:
    """(task-loop version to pin, delegate version to keep, why not): the newest install below the current one."""
    pin = read_pin()
    newest = max(cache_dirs("task-loop"), key=lambda v: version_tuple(v) or (), default="")
    cur = pin.task_loop or installed_version("task-loop") or newest
    if not cur:
        return "", "", "refused: no task-loop install to roll back from"
    prev = previous_version("task-loop", cur)
    if not prev:
        return "", "", f"refused: no task-loop version older than {cur} is installed"
    keep = pin.delegate or installed_version("delegate")
    return prev, keep if keep in cache_dirs("delegate") else "", ""


def run_pin(version: str | None, delegate: str | None, clear: bool) -> int:
    """`tl pin [VERSION] [--delegate V] [--clear]`: show, set or clear the pin."""
    if clear:
        if version or delegate:
            sys.exit("tl: pin --clear takes no version")
        print("PIN CLEARED" if clear_pin() else "no pin was set")
        return 0
    if not (version or delegate):
        pin = pin_store().get()
        print(json.dumps(pin.to_dict()) if pin else "no pin")
        return 0
    pin, why = set_pin(version or "", delegate or "")
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    print("PINNED " + " ".join(f"{k} {pin_version(pin, k)}" for k in ("task-loop", "delegate") if pin_version(pin, k)))
    return 0


def run_rollback() -> int:
    """`tl rollback`: pin the previous task-loop version (the delegate stays as it is)."""
    prev, keep, why = rollback_target()
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    return run_pin(prev, keep, False)
