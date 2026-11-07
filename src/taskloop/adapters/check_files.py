"""The files a check's cache key reads: a git tree's listing, the ignored files under some globs, a file's digest."""
import hashlib
import os
from collections.abc import Sequence
from pathlib import Path

from taskloop.contracts.gitport import Git
from taskloop.contracts.ids import loop_key
from taskloop.contracts.slots import SlotGitError

BIG = 16 * 1024 * 1024  # an ignored input bigger than this counts by size, not content


def tree_files(git: Git, wt: str, tree: str) -> dict[str, str]:
    """{path: "mode type sha"} for a git tree (every file under it); {} when git cannot list it."""
    try:
        return {t.path: f"{t.mode} {t.kind} {t.oid}" for t in git.ls_tree(wt, tree, recursive=True)}
    except SlotGitError:
        return {}


def ignored_files(git: Git, wt: str, spec: Sequence[str]) -> list[str]:
    """Ignored (untracked, gitignored) files in the worktree under the git pathspecs `spec` (all of them when empty)."""
    try:
        return git.ls_files(wt, "ignored", *spec)
    except SlotGitError:
        return []


def file_digest(path: str) -> str:
    h = hashlib.sha1()
    try:
        size = os.path.getsize(path)
        if size > BIG:
            return f"big:{size}"
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return "gone"
    return h.hexdigest()


def repo_key(git: Git, wt: str) -> str:
    """The repo's one key, shared by its slots, loop, checks and artifacts: ids.loop_key of the repo folder (the parent of the git
    common dir, the worktree when git cannot say), so a slot's worktree and the checkout name the same repo."""
    common = git.common_dir(wt)
    return loop_key(Path(common).parent if common else wt)


def read_lines(path: str | Path, n: int = 2000) -> list[str]:
    """The first n lines of a text file, [] when it cannot be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [ln.rstrip("\n") for _, ln in zip(range(n), f, strict=False)]
    except OSError:
        return []
