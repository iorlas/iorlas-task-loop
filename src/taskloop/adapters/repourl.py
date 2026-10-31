"""The one name of a repo that its slots, its worktrees and the loop's own checkout all share: the origin url, else the common git dir.
The storm record, the trace's repo, the land lock and the review lock key on it; a worktree's own path is no key (each slot has one)."""
from taskloop.contracts.ports import Git


def repo_url(git: Git, d: str) -> str:
    return git.remote_url(d, "origin") or git.common_dir(d) or d
