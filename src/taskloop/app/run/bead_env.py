"""The environment of every command a bead runs: its slot's (domain/slot_env), made once per run, the folders created on use."""
from pathlib import Path
from typing import Any

from taskloop.adapters.check_files import repo_key
from taskloop.contracts.slots import git_probe
from taskloop.domain import slot_env


def bead_env(e: Any, *, create: bool = True) -> dict[str, str]:
    """The slot's environment for the engine `e`. The slot is its worktree's name (a plain worktree is its own slot); the repo is the
    origin url's name, and its state folder is the repo's one key (adapters.check_files.repo_key)."""
    origin = git_probe(lambda: e.git.remote_url(e.wt, "origin"), "") or str(e.wt)
    repo, slot = slot_env.repo_id(origin, str(e.wt)), Path(str(e.wt)).name
    state = e.home.slot_state(repo_key(e.git, str(e.wt)), slot)
    env = slot_env.slot_env(state, repo, slot, e.cfg.slot_env)
    for folder in slot_env.folders(env, state) if create else []:
        Path(folder).mkdir(parents=True, exist_ok=True)
    return env
