"""git on a checkout: the environment that pins git to that checkout, and the one helper that runs it there."""
import re
import subprocess
from pathlib import Path
from typing import Any

from taskloop.adapters.childenv import tool_env
from taskloop.contracts import env as penv


def pinned_env(path: str | Path) -> dict[str, str]:
    """GIT_DIR and GIT_WORK_TREE of the checkout at `path` (its nearest parent with a .git), read from its own `.git`
    (a slot's `.git` file says `gitdir: <its dir under the repo's .git/worktrees>`). With both set git ignores the
    repo's shared config: a core.worktree written into .git/config (lifesim-1mm) pointed every slot at another folder.
    {} when `path` is no checkout."""
    p = Path(path).resolve()
    for d in (p, *p.parents):
        g = d / ".git"
        if g.is_dir():
            return {"GIT_DIR": str(g), "GIT_WORK_TREE": str(d)}
        if g.is_file():
            try:
                m = re.match(r"gitdir:\s*(.+)", g.read_text(encoding="utf-8", errors="replace").strip())
            except OSError:
                return {}
            return {"GIT_DIR": str((d / m.group(1)).resolve()), "GIT_WORK_TREE": str(d)} if m else {}
    return {}


def git_env(path: str | Path) -> dict[str, str]:
    """The environment for a git command on the checkout at `path`: the process's, pinned to that checkout."""
    return tool_env(penv.snapshot().vars, pinned_env(path))


def run_git(path: str | Path, *args: str, **kw: Any) -> subprocess.CompletedProcess[Any]:
    """`git -C path args`, pinned to the checkout at `path` (the one helper for subprocess git calls on a checkout)."""
    return subprocess.run(["git", "-C", str(path), *args], env=git_env(path), check=False, **kw)
