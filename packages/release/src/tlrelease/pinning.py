"""Owner commands that authorize and change the standing release pin."""
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.paths import ConfigDir
from tlkernel.snapshots import Pin

from tlrelease.canary import mac_pin_refusal
from tlrelease.catalog import PLUGIN, cache_dirs, installed_version, previous_version, version_tuple
from tlrelease.pins import clear_pin, pin_store, pin_version, read_pin


class PinPaths(Protocol):
    @property
    def plugin_root(self) -> Path: ...

    @property
    def config_dir(self) -> Callable[[Env], Path]: ...

    @property
    def claude_dir(self) -> Callable[[Env], Path]: ...


def pin_refusal(claude: Path, root: Path, version: str, old: Pin, git: Git | None) -> str:
    current = old.task_loop or installed_version(claude) or max(cache_dirs(claude), key=lambda v: version_tuple(v) or (), default="")
    if current and (version_tuple(version) or ()) < (version_tuple(current) or ()):
        return ""
    if git is None:
        return "refused: a git port is required to read origin's devbox acknowledgement"
    try:
        url = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["repository"]
    except (OSError, ValueError, KeyError) as e:
        return f"refused: cannot find the release origin: {e}"
    return mac_pin_refusal(root, url, version, git)


def on_mac() -> bool:
    """A seam: tests pretend to be a Mac without changing sys.platform, which the database layer reads to judge the filesystem."""
    return sys.platform == "darwin"


def set_pin(env: Env, task_loop: str = "", git: Git | None = None, *, host: PinPaths) -> tuple[Pin, str]:
    """(the pin now, "" or why it is refused): a version that is not installed is refused, never pinned."""
    old = read_pin(ConfigDir(host.config_dir(env)))
    if on_mac() and task_loop and task_loop != old.task_loop:
        why = pin_refusal(host.claude_dir(env), host.plugin_root, task_loop, old, git)
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


def rollback_target(home: ConfigDir, claude: Path) -> tuple[str, str]:
    """(task-loop version to pin, why not): the newest install below the current one."""
    pin = read_pin(home)
    newest = max(cache_dirs(claude), key=lambda v: version_tuple(v) or (), default="")
    cur = pin.task_loop or installed_version(claude) or newest
    if not cur:
        return "", "refused: no task-loop install to roll back from"
    prev = previous_version(cur, claude)
    if not prev:
        return "", f"refused: no task-loop version older than {cur} is installed"
    return prev, ""


def run_pin(env: Env, version: str | None, clear: bool, git: Git | None = None, *, host: PinPaths) -> int:
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


def run_rollback(env: Env, git: Git | None = None, *, host: PinPaths) -> int:
    """`tl rollback`: pin the previous task-loop version."""
    prev, why = rollback_target(ConfigDir(host.config_dir(env)), host.claude_dir(env))
    if why:
        print("tl: " + why, file=sys.stderr)
        return 2
    return run_pin(env, prev, False, git, host=host)
