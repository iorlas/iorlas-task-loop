"""pinned.json ({"task-loop": "0.23.38", "delegate": "0.40.1"}, each key optional) is written by `tl pin` and `tl rollback` only: the
owner's override. The loop reads it, never writes it. A pin names a plugin cache dir that must exist."""
import json
import sys
import time

from taskloop.adapters.ident import PLUGIN_ROOT, claude_dir, config_dir
from taskloop.app.release.canary import mac_pin_refusal
from taskloop.app.release.catalog import PLUGINS, cache_dirs, installed_version, previous_version, version_tuple
from taskloop.contracts.env import Env
from taskloop.contracts.gitport import Git
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.rowstores import PinStore
from taskloop.contracts.snapshots import Pin


def pin_store(env: Env) -> PinStore:
    return PinStore(ConfigDir(config_dir(env)))


def read_pin(env: Env) -> Pin:
    """The pin (an empty one when there is none, or the file is not a Pin of this version)."""
    return pin_store(env).get() or Pin()


def pin_version(pin: Pin, key: str) -> str:
    return (pin.task_loop if key == "task-loop" else pin.delegate) or ""


def clear_pin(env: Env) -> bool:
    """Remove the pin; True when there was one."""
    had = pin_store(env).get() is not None
    pin_store(env).delete()
    return had


def pin_refusal(env: Env, version: str, old: Pin, git: Git | None) -> str:
    claude = claude_dir(env)
    current = old.task_loop or installed_version("task-loop", claude) or max(
        cache_dirs("task-loop", claude), key=lambda v: version_tuple(v) or (), default="")
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


def set_pin(env: Env, task_loop: str = "", delegate: str = "", git: Git | None = None) -> tuple[Pin, str]:
    """(the pin now, "" or why it is refused): a version that is not installed is refused, never pinned."""
    old = read_pin(env)
    if on_mac() and task_loop and task_loop != old.task_loop:
        why = pin_refusal(env, task_loop, old, git)
        if why:
            return old, why
    want = {"task-loop": task_loop, "delegate": delegate}
    for key, v in want.items():
        if v and v not in cache_dirs(key, claude_dir(env)):
            have = sorted(cache_dirs(key, claude_dir(env)), key=lambda x: version_tuple(x) or ())
            return read_pin(env), "refused: {} {} is not installed under {} (installed: {})".format(
                PLUGINS[key][0], v, claude_dir(env) / "plugins" / "cache", ", ".join(have) or "none")
    pin = old.replace(task_loop=task_loop or old.task_loop, delegate=delegate or old.delegate, pinned_at=time.time())
    pin_store(env).write(pin)
    return pin, ""


def rollback_target(env: Env) -> tuple[str, str, str]:
    """(task-loop version to pin, delegate version to keep, why not): the newest install below the current one."""
    claude = claude_dir(env)
    pin = read_pin(env)
    newest = max(cache_dirs("task-loop", claude), key=lambda v: version_tuple(v) or (), default="")
    cur = pin.task_loop or installed_version("task-loop", claude) or newest
    if not cur:
        return "", "", "refused: no task-loop install to roll back from"
    prev = previous_version("task-loop", cur, claude)
    if not prev:
        return "", "", f"refused: no task-loop version older than {cur} is installed"
    keep = pin.delegate or installed_version("delegate", claude)
    return prev, keep if keep in cache_dirs("delegate", claude) else "", ""


def run_pin(env: Env, version: str | None, delegate: str | None, clear: bool, git: Git | None = None) -> int:
    """`tl pin [VERSION] [--delegate V] [--clear]`: show, set or clear the pin."""
    if clear:
        if version or delegate:
            sys.exit("tl: pin --clear takes no version")
        print("PIN CLEARED" if clear_pin(env) else "no pin was set")
        return 0
    if not (version or delegate):
        pin = pin_store(env).get()
        print(json.dumps(pin.to_dict()) if pin else "no pin")
        return 0
    pin, why = set_pin(env, version or "", delegate or "", git)
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    print("PINNED " + " ".join(f"{k} {pin_version(pin, k)}" for k in ("task-loop", "delegate") if pin_version(pin, k)))
    return 0


def run_rollback(env: Env, git: Git | None = None) -> int:
    """`tl rollback`: pin the previous task-loop version (the delegate stays as it is)."""
    prev, keep, why = rollback_target(env)
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    return run_pin(env, prev, keep, False, git)
