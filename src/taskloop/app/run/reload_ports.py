"""Root bindings for installed versions and the engine lock."""
from pathlib import Path

from tlkernel.env import Env
from tlkernel.paths import ConfigDir
from tlrelease import catalog, pins
from tlslots.engine_lock import HeldLock

from taskloop.adapters import ident
from taskloop.app.launch.release_host import release_host
from taskloop.app.loop.versions import Installs
from taskloop.app.track import trail


def installed_newer(env: Env, root: Path = ident.PLUGIN_ROOT) -> tuple[str, Path] | None:
    """(version, dir) of the install the loop would move to, or None: the engine's step-boundary look."""
    found = Installs(ConfigDir(ident.config_dir(env)), root, lambda: catalog.installed_version(ident.claude_dir(env)),
                     lambda: pins.read_pin(env, host=release_host()).task_loop or "", now=trail.now).move_to()
    return (found.version, found.dir) if found else None


def locked_slot(held: HeldLock) -> str:
    return held.slot
