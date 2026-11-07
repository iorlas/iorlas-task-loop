"""Root bindings for installed versions and the engine lock."""

from pathlib import Path

from tlkernel.env import Env
from tlkernel.paths import ConfigDir
from tlrelease import catalog
from tlslots.engine_lock import HeldLock

from taskloop.adapters import ident
from taskloop.app.track import trail


def installed_newer(env: Env, root: Path = ident.PLUGIN_ROOT) -> tuple[str, Path] | None:
    """(version, dir) of the install the loop would move to, or None: the engine's step-boundary look."""
    return catalog.installed_newer(ConfigDir(ident.config_dir(env)), root, lambda: ident.claude_dir(env), trail.now)


def locked_slot(held: HeldLock) -> str:
    return held.slot
