"""Temporary detached checkouts for the land gate and checks against the untouched base."""
import contextlib
import tempfile
from collections.abc import Generator
from pathlib import Path

from tlkernel.gitport import Git
from tlkernel.slots import SlotGitError


@contextlib.contextmanager
def clean_tree(git: Git, wt: str | Path, sha: str) -> Generator[Path]:
    """A fresh detached checkout, with no slot files copied in; creation failures propagate without a fallback."""
    with tempfile.TemporaryDirectory(prefix="tl-gate-") as tmp:
        dest = Path(tmp) / "tree"
        try:
            git.add_worktree(str(wt), str(dest), sha)
            yield dest
        finally:
            git.remove_worktree_force(str(wt), str(dest))


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
