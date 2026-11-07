"""pinned.json ({"task-loop": "0.23.38"}, version optional) is written by `tl pin` and `tl rollback` only: the
owner's override. The loop reads it, never writes it. A pin names a plugin cache dir that must exist."""

import json
import sys
import time

from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.paths import ConfigDir
from tlkernel.rowstores import PinStore
from tlkernel.snapshots import Pin

from tlrelease.canary import mac_pin_refusal
from tlrelease.catalog import PLUGIN, cache_dirs, installed_version, previous_version, version_tuple
from tlrelease.host import ReleaseHost


def pin_store(home: ConfigDir) -> PinStore:
    return PinStore(home)


def read_pin(home: ConfigDir) -> Pin:
    """The pin (an empty one when there is none, or the file is not a Pin of this version)."""
    return pin_store(home).get() or Pin()


def pin_version(pin: Pin) -> str:
    return pin.task_loop or ""


def clear_pin(home: ConfigDir) -> bool:
    """Remove the pin; True when there was one."""
    had = pin_store(home).get() is not None
    pin_store(home).delete()
    return had


def pin_refusal(env: Env, version: str, old: Pin, git: Git | None, *, host: ReleaseHost) -> str:
    claude = host.claude_dir(env)
    current = old.task_loop or installed_version(claude) or max(cache_dirs(claude), key=lambda v: version_tuple(v) or (), default="")
    if current and (version_tuple(version) or ()) < (version_tuple(current) or ()):
        return ""
    if git is None:
        return "refused: a git port is required to read origin's devbox acknowledgement"
    try:
        url = json.loads((host.plugin_root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["repository"]
    except (OSError, ValueError, KeyError) as e:
        return f"refused: cannot find the release origin: {e}"
    return mac_pin_refusal(host.plugin_root, url, version, git)


def on_mac() -> bool:
    """A seam: tests pretend to be a Mac without changing sys.platform, which the database layer reads to judge the filesystem."""
    return sys.platform == "darwin"


def set_pin(env: Env, task_loop: str = "", git: Git | None = None, *, host: ReleaseHost) -> tuple[Pin, str]:
    """(the pin now, "" or why it is refused): a version that is not installed is refused, never pinned."""
    old = read_pin(ConfigDir(host.config_dir(env)))
    if on_mac() and task_loop and task_loop != old.task_loop:
        why = pin_refusal(env, task_loop, old, git, host=host)
        if why:
            return old, why
    if task_loop and task_loop not in cache_dirs(host.claude_dir(env)):
        have = sorted(cache_dirs(host.claude_dir(env)), key=lambda x: version_tuple(x) or ())
        return old, "refused: {} {} is not installed under {} (installed: {})".format(
            PLUGIN, task_loop, host.claude_dir(env) / "plugins" / "cache", ", ".join(have) or "none"
        )
    pin = old.replace(task_loop=task_loop or old.task_loop, pinned_at=time.time())
    pin_store(ConfigDir(host.config_dir(env))).write(pin)
    return pin, ""


def rollback_target(env: Env, *, host: ReleaseHost) -> tuple[str, str]:
    """(task-loop version to pin, why not): the newest install below the current one."""
    claude = host.claude_dir(env)
    pin = read_pin(ConfigDir(host.config_dir(env)))
    newest = max(cache_dirs(claude), key=lambda v: version_tuple(v) or (), default="")
    cur = pin.task_loop or installed_version(claude) or newest
    if not cur:
        return "", "refused: no task-loop install to roll back from"
    prev = previous_version(cur, claude)
    if not prev:
        return "", f"refused: no task-loop version older than {cur} is installed"
    return prev, ""


def run_pin(env: Env, version: str | None, clear: bool, git: Git | None = None, *, host: ReleaseHost) -> int:
    """`tl pin [VERSION] [--clear]`: show, set or clear the pin."""
    if clear:
        if version:
            sys.exit("tl: pin --clear takes no version")
        print("PIN CLEARED" if clear_pin(ConfigDir(host.config_dir(env))) else "no pin was set")
        return 0
    if not version:
        pin = pin_store(ConfigDir(host.config_dir(env))).get()
        print(json.dumps(pin.to_dict()) if pin else "no pin")
        return 0
    pin, why = set_pin(env, version, git, host=host)
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    print("PINNED task-loop " + pin_version(pin))
    return 0


def run_rollback(env: Env, git: Git | None = None, *, host: ReleaseHost) -> int:
    """`tl rollback`: pin the previous task-loop version."""
    prev, why = rollback_target(env, host=host)
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    return run_pin(env, prev, False, git, host=host)
