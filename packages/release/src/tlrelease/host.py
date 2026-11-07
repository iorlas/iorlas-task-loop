"""Machine effects supplied by the shell to release orchestration.

config_dir effect: creates the machine config directory / stays outside because the shell owns machine layout.
claude_dir effect: locates Claude configuration / stays outside because the shell owns installation layout.
identity effect: reads session and machine identity / stays outside because the shell chooses the actor.
plugin_root effect: locates the running installation / stays outside because the shell owns its entry path.
land_lock_path effect: names the shared land lock / stays outside because land and release share shell lock policy.
os_lock effect: holds an OS file lock / stays outside because the shell owns process coordination.
bd_store effect: opens the actor's bead store / stays outside because the shell owns the bd adapter.
repo_root effect: resolves a checkout through git / stays outside because the shell owns repository discovery.
"""
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from tlkernel.beadsport import Beads
from tlkernel.env import Env
from tlkernel.identity import Identity
from tlkernel.paths import ConfigDir


@dataclass(frozen=True)
class ReleaseHost:
    config_dir: Callable[[Env], Path]
    claude_dir: Callable[[Env], Path]
    identity: Callable[[Env], Identity]
    plugin_root: Path
    land_lock_path: Callable[[ConfigDir, str], Path]
    os_lock: Callable[[Path, str, Callable[[str], None]], AbstractContextManager[Path | str]]
    bd_store: Callable[[str, Path], Beads]
    repo_root: Callable[[str], str]
