"""Path listings and ignore queries, NUL framed so filenames remain intact."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain.porcelain import run_git
from git_porcelain.real import RealRepo
from git_porcelain.real_done import unavailable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def check_ignore(repo: Path, paths: Sequence[str]) -> set[str]:
    """Paths ignored by the checkout's rules, even when already tracked (``--no-index``)."""
    if not paths:
        return set()
    done = RealRepo(repo).run(repo, "check-ignore", "--no-index", "--stdin", "-z", stdin="\0".join(paths) + "\0", check=False)
    if done.rc not in (0, 1):
        raise unavailable(("check-ignore",), done)
    return {p for p in done.out.split("\0") if p}


def ls_files(repo: Path, *, scope: str = "tracked") -> list[str]:
    """Sorted repo-relative paths: tracked (index), untracked, ignored, or all three."""
    options = {
        "tracked": ("--cached",),
        "untracked": ("--others", "--exclude-standard"),
        "ignored": ("--others", "--ignored", "--exclude-standard"),
        "all": ("--cached", "--others"),
    }
    if scope not in options:
        msg = f"unknown file scope: {scope!r}"
        raise ValueError(msg)
    out = run_git(repo, "ls-files", "-z", *options[scope])
    return sorted({p for p in out.split("\0") if p})
