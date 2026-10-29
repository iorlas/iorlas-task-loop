"""The repo a verb works on: its root from the current directory, and the base branch its profile names."""
from taskloop.adapters import gitrepo
from taskloop.app.wire import slots as wslots


def repo_root(path: str | None = None) -> str:
    return gitrepo.repo_root(path)


def default_base(repo: str) -> str:
    return wslots.load_cfg(repo).base
