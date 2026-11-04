"""Config reads preserve embedded newlines and distinguish absence from a failed read."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain.real import RealRepo
from git_porcelain.real_observe import read_config

if TYPE_CHECKING:
    from pathlib import Path


def config_get(repo: Path, key: str, default: str | None = None) -> str | None:
    """The last configured value for ``key``, or ``default`` when absent."""
    out = read_config(RealRepo(repo), "--get", key)
    return default if out is None else out.removesuffix("\0")


def config_entries(repo: Path, pattern: str) -> list[tuple[str, str]]:
    """All matching config entries in git's order, including repeated keys and multiline values."""
    out = read_config(RealRepo(repo), "--get-regexp", pattern)
    if out is None:
        return []
    return [(key, value) for key, _, value in (row.partition("\n") for row in out.split("\0") if row)]
