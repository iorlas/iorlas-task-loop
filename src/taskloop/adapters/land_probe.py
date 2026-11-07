"""Observe the shared land lock for the pre-push shell binder."""
from taskloop.adapters import landlock, locks
from tlkernel.gitport import Git
from tlkernel.locks import LockTimeout
from tlkernel.paths import ConfigDir
from tlkernel.slots import MissingRemote


def land_lock_held(home: ConfigDir, git: Git, repo: str) -> bool:
    """Whether someone holds the repo's land lock now: a land push and a release take it around their push to the base branch."""
    try:
        url = git.remote_url(repo, "origin")
    except MissingRemote:
        url = ""
    try:
        with locks.hold_path(landlock.land_lock_path(home, url or repo), "judge-probe", timeout=0):
            return False
    except LockTimeout:
        return True
