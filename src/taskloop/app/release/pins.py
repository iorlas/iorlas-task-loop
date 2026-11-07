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

from taskloop.adapters.ident import PLUGIN_ROOT, claude_dir, config_dir
from taskloop.app.release.canary import mac_pin_refusal
from taskloop.app.release.catalog import PLUGIN, cache_dirs, installed_version, previous_version, version_tuple


def pin_store(env: Env) -> PinStore:
    return PinStore(ConfigDir(config_dir(env)))


def read_pin(env: Env) -> Pin:
    """The pin (an empty one when there is none, or the file is not a Pin of this version)."""
    return pin_store(env).get() or Pin()


def pin_version(pin: Pin) -> str:
    return pin.task_loop or ""


def clear_pin(env: Env) -> bool:
    """Remove the pin; True when there was one."""
    had = pin_store(env).get() is not None
    pin_store(env).delete()
    return had


def pin_refusal(env: Env, version: str, old: Pin, git: Git | None) -> str:
    claude = claude_dir(env)
    current = old.task_loop or installed_version(claude) or max(
        cache_dirs(claude), key=lambda v: version_tuple(v) or (), default="")
    if current and (version_tuple(version) or ()) < (version_tuple(current) or ()):
        return ""
    if git is None:
        return "refused: a git port is required to read origin's devbox acknowledgement"
    try:
        url = json.loads((PLUGIN_ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["repository"]
    except (OSError, ValueError, KeyError) as e:
        return f"refused: cannot find the release origin: {e}"
    return mac_pin_refusal(PLUGIN_ROOT, url, version, git)


def on_mac() -> bool:
    """A seam: tests pretend to be a Mac without changing sys.platform, which the database layer reads to judge the filesystem."""
    return sys.platform == "darwin"


def set_pin(env: Env, task_loop: str = "", git: Git | None = None) -> tuple[Pin, str]:
    """(the pin now, "" or why it is refused): a version that is not installed is refused, never pinned."""
    old = read_pin(env)
    if on_mac() and task_loop and task_loop != old.task_loop:
        why = pin_refusal(env, task_loop, old, git)
        if why:
            return old, why
    if task_loop and task_loop not in cache_dirs(claude_dir(env)):
        have = sorted(cache_dirs(claude_dir(env)), key=lambda x: version_tuple(x) or ())
        return old, "refused: {} {} is not installed under {} (installed: {})".format(
            PLUGIN, task_loop, claude_dir(env) / "plugins" / "cache", ", ".join(have) or "none")
    pin = old.replace(task_loop=task_loop or old.task_loop, pinned_at=time.time())
    pin_store(env).write(pin)
    return pin, ""


def rollback_target(env: Env) -> tuple[str, str]:
    """(task-loop version to pin, why not): the newest install below the current one."""
    claude = claude_dir(env)
    pin = read_pin(env)
    newest = max(cache_dirs(claude), key=lambda v: version_tuple(v) or (), default="")
    cur = pin.task_loop or installed_version(claude) or newest
    if not cur:
        return "", "refused: no task-loop install to roll back from"
    prev = previous_version(cur, claude)
    if not prev:
        return "", f"refused: no task-loop version older than {cur} is installed"
    return prev, ""


def run_pin(env: Env, version: str | None, clear: bool, git: Git | None = None) -> int:
    """`tl pin [VERSION] [--clear]`: show, set or clear the pin."""
    if clear:
        if version:
            sys.exit("tl: pin --clear takes no version")
        print("PIN CLEARED" if clear_pin(env) else "no pin was set")
        return 0
    if not version:
        pin = pin_store(env).get()
        print(json.dumps(pin.to_dict()) if pin else "no pin")
        return 0
    pin, why = set_pin(env, version, git)
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    print("PINNED task-loop " + pin_version(pin))
    return 0


def run_rollback(env: Env, git: Git | None = None) -> int:
    """`tl rollback`: pin the previous task-loop version."""
    prev, why = rollback_target(env)
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    return run_pin(env, prev, False, git)
