"""Refuse trust-root changes before review and land unless the bead is owner-approved.

Because this runs before the reviewer, changed worktree trust roots can only reach the
reviewer's prompt when the owner approved the change. This closes the injection path
for unapproved changes; base-copy reviewer instructions belong to delegate.
"""
from typing import Final

from tlkernel.bead import Bead
from tlkernel.gitport import Git
from tlkernel.slots import GitReadFailure

OWNER_APPROVED: Final = "owner-approved"
FILES: Final = frozenset(("AGENTS.md", "CLAUDE.md", "mise.toml", ".task-loop.json"))
DIRECTORIES: Final = (".claude", ".codex", "githooks")


def protected(path: str) -> bool:
    return path in FILES or any(path == root or path.startswith(root + "/") for root in DIRECTORIES)


def refusal(git: Git, wt: str, base: str, bead: Bead | None) -> str:
    """The whole bead's diff, including uncommitted and untracked files; failed reads never authorize it."""
    if bead is None:
        return "trust roots: bead unavailable; cannot verify the owner-approved label"
    start = git.merge_base(wt, base, "HEAD")
    tree = git.tree_of(wt)
    if not start or not tree:
        raise GitReadFailure("trust roots: cannot resolve the bead base or candidate tree")
    entries = git.diff_entries(wt, start, tree, required=True)
    paths = sorted({p for entry in entries for p in (entry.old, entry.path) if protected(p)})
    if paths and OWNER_APPROVED not in bead.labels:
        return f"trust roots changed without owner-approved: {', '.join(paths)}; owner must approve and label the bead, or revert them"
    return ""
