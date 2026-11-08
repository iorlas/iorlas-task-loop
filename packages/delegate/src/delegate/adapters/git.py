"""The only code that runs git for delegate: the repo root of a folder, and the HEAD and branch a worker must leave alone."""

# git-port-exempt: delegate is a plugin of its own and has no Git port; this module is its one git reader (rev-parse and symbolic-ref only)

import os
import shutil
import subprocess
from pathlib import Path

from delegate.adapters import procs

GIT_S = 120  # a rev-parse that takes longer is a hung repository, read as "not a work tree"


def _git(cwd: object, *args: str) -> str | None:
    try:
        r = procs.run_capture(["git", "-C", str(cwd), *args], GIT_S)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout if r.returncode == 0 else None


def repo_root(cwd: str | os.PathLike[str]) -> Path:
    """The work tree's top folder, or cwd resolved when it is not in one."""
    wd = Path(cwd).resolve()
    top = (_git(wd, "rev-parse", "--show-toplevel") or "").strip() if shutil.which("git") else ""
    return Path(top).resolve() if top else wd


def show(cwd: object, ref: str, path: str) -> str | None:
    """The text of `path` as committed at `ref` (a commit sha), None when the commit has no such file or git cannot answer. Never reads
    the work tree."""
    return _git(cwd, "show", f"{ref}:{path}")


def prefix(cwd: object) -> str:
    """cwd's path under the repo root with a trailing slash ('' at the root or outside a repo): what `ref:<prefix>FILE` needs."""
    return (_git(cwd, "rev-parse", "--show-prefix") or "").strip()


def state(cwd: object) -> dict[str, str] | None:
    """HEAD and current branch of cwd, or None when cwd is not a git work tree. Other refs and worktrees change while parallel slots
    work and land, so they are not compared."""
    if shutil.which("git") is None or _git(cwd, "rev-parse", "--is-inside-work-tree") is None:
        return None
    return {
        "head": (_git(cwd, "rev-parse", "HEAD") or "").strip(),
        "branch": (_git(cwd, "symbolic-ref", "-q", "--short", "HEAD") or "").strip(),
    }


def changes(before: dict[str, str] | None, after: dict[str, str] | None) -> list[str]:
    """-> human-readable differences; empty when the worker left HEAD and branch alone."""
    if before is None or after is None:
        return []
    out: list[str] = []
    if before["branch"] != after["branch"]:
        out.append(f"branch {before['branch'] or '(detached)'} -> {after['branch'] or '(detached)'}")
    if before["head"] != after["head"]:
        out.append(f"HEAD {before['head'][:9]} -> {after['head'][:9]}")
    return out
