"""A clean checkout of a commit, for asking whether a check was already red before the task touched anything."""
import contextlib
import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path


@contextlib.contextmanager
def base_tree(wt: str | Path, sha: str, dest: Path, env: Mapping[str, str]) -> Iterator[Path | None]:
    """`dest` holds the commit `sha` for the `with` block (a detached git worktree of the repo of `wt`); None when git could not make it."""
    made = subprocess.run(["git", "worktree", "add", "--detach", "--force", str(dest), sha], cwd=str(wt), env=dict(env),
                          capture_output=True, check=False)
    try:
        yield dest if made.returncode == 0 else None
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(dest)], cwd=str(wt), env=dict(env), capture_output=True, check=False)
        subprocess.run(["git", "worktree", "prune"], cwd=str(wt), env=dict(env), capture_output=True, check=False)
