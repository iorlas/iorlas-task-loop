"""Config reads preserve embedded newlines and distinguish absence from a failed read."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain.real import RealRepo
from git_porcelain.real_done import unavailable

if TYPE_CHECKING:
    from pathlib import Path


def _read(repo: Path, *args: str) -> str | None:
    done = RealRepo(repo).run(repo, "config", "--null", *args, check=False)
    if done.rc == 1 and not done.out and not done.err:
        return None
    if done.rc:
        raise unavailable(("config",), done)
    return done.out


def config_get(repo: Path, key: str, default: str | None = None) -> str | None:
    """The last configured value for ``key``, or ``default`` when absent."""
    out = _read(repo, "--get", key)
    return default if out is None else out.removesuffix("\0")


def config_entries(repo: Path, pattern: str) -> list[tuple[str, str]]:
    """All matching config entries in git's order, including repeated keys and multiline values."""
    out = _read(repo, "--get-regexp", pattern)
    if out is None:
        return []
    return [(key, value) for key, _, value in (row.partition("\n") for row in out.split("\0") if row)]
