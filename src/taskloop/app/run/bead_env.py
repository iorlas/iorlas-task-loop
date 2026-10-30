"""The environment of every command a bead runs: its slot's (domain/slot_env), made once per run, the folders created on use."""
import hashlib
from pathlib import Path
from typing import Any

from taskloop.domain import slot_env


def bead_env(e: Any) -> dict[str, str]:
    """The slot's environment for the engine `e`. The slot is its worktree's name (a plain worktree is its own slot); the repo is the
    origin url's name, and its state folder adds a hash of the url so two repos of one name never meet."""
    origin = e.git.remote_url(e.wt, "origin") or str(e.wt)
    repo, slot = slot_env.repo_id(origin, str(e.wt)), Path(str(e.wt)).name
    key = f"{repo}-{hashlib.sha1(origin.encode('utf-8', 'surrogateescape')).hexdigest()[:10]}"
    state = e.home.slot_state(key, slot)
    env = slot_env.slot_env(state, repo, slot, e.cfg.slot_env)
    for folder in slot_env.folders(env):
        Path(folder).mkdir(parents=True, exist_ok=True)
    return env
