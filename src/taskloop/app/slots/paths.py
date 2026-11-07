"""Paths owned by taskloop.app.slots."""
from pathlib import Path

from tlkernel.ids import loop_key
from tlkernel.paths import ConfigDir


def engine_lock(cfg: ConfigDir, wt: Path | str) -> Path:
    """The engine lock of a worktree: out of the tree, where no worker can write it (Z15). Keyed like the loop's files."""
    return cfg.lock_record("engine", loop_key(wt))


def engine_take(cfg: ConfigDir, wt: Path | str) -> Path:
    """Held (locks.hold_path) while a run checks the engine lock and writes its own: two runs starting at once cannot both win."""
    return cfg.lock_record("engine-take", loop_key(wt))


def slot_setup_mark(cfg: ConfigDir, key: str) -> Path:
    return cfg.root / "slots" / (f"{key}.setup")


def slot_state(cfg: ConfigDir, repo_key: str, slot: str) -> Path:
    """What one slot of one repo keeps for its commands (temp, dotnet and NuGet scratch): outside the worktree, kept across reuse."""
    return cfg.repo_dir(repo_key) / "slot-state" / slot


def slot_state_roots(cfg: ConfigDir) -> list[Path]:
    """Every repo's slot-state folder that exists: the parent of each slot's scratch."""
    return sorted(cfg.repos_dir().glob("*/slot-state"))
