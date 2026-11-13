"""The one place that asks Git which files changed. Stdlib only, so a no-op run never loads the heavy imports.

Prototype: the real port would sit on shelf's git-porcelain. Callers take a `ChangedPaths` callable and tests pass a fake."""

import subprocess
from collections.abc import Callable
from pathlib import Path

type ChangedPaths = Callable[[Path, str], list[Path]]


def _git(directory: Path, *args: str) -> list[str]:
    done = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True, check=False)
    return done.stdout.splitlines() if done.returncode == 0 else []


def changed_paths(directory: Path, base: str) -> list[Path]:
    """Files changed against the merge-base with `base` (committed or not), plus untracked files; absolute, sorted."""
    top = _git(directory, "rev-parse", "--show-toplevel")
    if not top:
        return []
    merge_base = _git(directory, "merge-base", "HEAD", base)
    names = _git(directory, "diff", "--name-only", merge_base[0] if merge_base else "HEAD")
    names += _git(directory, "ls-files", "--others", "--exclude-standard")
    return sorted({Path(top[0]) / name for name in names})
