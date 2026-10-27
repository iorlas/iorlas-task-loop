"""RealGit's environment: what every git child inherits, and what a checkout pins.

The ambient set (``base``) strips the variables that would aim git at another repository and turns off
prompts, so a missing credential fails loud instead of hanging. ``pinned`` adds ``GIT_DIR`` and
``GIT_WORK_TREE`` read from the checkout's ``.git`` entry, so a stray ``core.worktree`` in a shared config
cannot redirect a slot; only ``Worktree.health`` runs without the pin, on purpose: it asks what a worker's own
git would see. The user's config is left alone (credential helpers, ``insteadOf`` and signing must keep working);
the hermetic test env is ``git_porcelain.testing``'s business.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["LEAKS", "argv_prefix", "base", "common_of", "git_dir", "pinned"]

#: Variables git honours that would point a child at another repository, index or config.
LEAKS: Final = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_CONFIG_PARAMETERS",
    "GIT_PREFIX",
)
_GITDIR_FILE: Final = re.compile(r"gitdir:\s*(.+)")


def base(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The ambient environment of a git child, plus ``extra``."""
    env = {k: v for k, v in os.environ.items() if k not in LEAKS}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    env["LC_ALL"] = "C"
    env.update(extra or {})
    return env


def git_dir(checkout: Path) -> Path | None:
    """The git directory of ``checkout`` read from its ``.git`` entry (a folder, or a ``gitdir:`` file); None when
    there is none. No git process."""
    entry = checkout / ".git"
    if entry.is_dir():
        return entry
    try:
        text = entry.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = _GITDIR_FILE.match(text.strip())
    return (checkout / found[1].strip()).resolve() if found else None


def common_of(gitdir: Path) -> Path:
    """The git directory every worktree of the repository shares."""
    try:
        pointer = (gitdir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        return gitdir
    return (gitdir / pointer).resolve()


def pinned(checkout: Path) -> dict[str, str]:
    """``GIT_DIR`` and ``GIT_WORK_TREE`` for ``checkout``; empty when it has no ``.git`` entry."""
    found = git_dir(checkout)
    return {} if found is None else {"GIT_DIR": str(found), "GIT_WORK_TREE": str(checkout)}


def argv_prefix(checkout: Path, pin: Mapping[str, str]) -> list[str]:
    """``git -C <checkout> -c safe.directory=...``: a slot owned by another uid, or a CI checkout, still works."""
    safe = {str(checkout)}
    if "GIT_DIR" in pin:
        safe.add(str(common_of(Path(pin["GIT_DIR"]))))
    args = ["git", "-C", str(checkout)]
    for path in sorted(safe):
        args += ["-c", f"safe.directory={path}"]
    return args
