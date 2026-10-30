"""A clean checkout of a commit, for asking whether a check was already red before the task touched anything."""
import contextlib
from collections.abc import Generator
from pathlib import Path

from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError


@contextlib.contextmanager
def base_tree(git: Git, wt: str | Path, sha: str, dest: Path) -> Generator[Path | None]:
    """`dest` holds the commit `sha` for the `with` block (a detached git worktree of the repo of `wt`); None when git could not make it."""
    made = True
    try:
        git.add_worktree_force(str(wt), str(dest), sha)
    except SlotGitError:
        made = False
    try:
        yield dest if made else None
    finally:
        git.remove_worktree_force(str(wt), str(dest))
        git.prune_worktrees(str(wt))
