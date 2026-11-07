"""The repo a verb works on: its root from the current directory, and the base branch its profile names."""
from tlkernel.gitport import Git

from taskloop.adapters import gitrepo
from taskloop.app.slots import config as wslots_config


def repo_root(path: str | None = None) -> str:
    return gitrepo.repo_root(path)


def default_base(repo: str, git: Git) -> str:
    return wslots_config.load_cfg(repo, git).base
