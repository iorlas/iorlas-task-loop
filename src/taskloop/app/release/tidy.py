"""Leftovers of a branch that has landed: its worktrees and the branch itself. Plain `git worktree remove` only (it refuses a tree with
changes or untracked files, and a locked one), never --force; the branch goes only when patch for patch it is on origin/main.
All of it through the Git port."""
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError

BASE = "origin/main"


def on_base(git: Git, repo: str, ref: str, base: str = BASE) -> bool:
    """True when every commit of `ref` is on `base` by patch (git cherry: a branch replayed by a release is no ancestor but all `-`).
    False when git cannot say."""
    try:
        return all(p.upstream for p in git.cherry(repo, base, ref))
    except SlotGitError:
        return False


def tip_of(git: Git, repo: str, branch: str) -> str:
    """The oid a local branch is at now, "" when there is none."""
    return git.rev_parse(repo, "refs/heads/" + branch)


def delete_branch_at(git: Git, repo: str, branch: str, oid: str) -> str:
    """Delete a local branch only while it is still at `oid`, the commit that was checked (compare and delete: a commit added since
    keeps the branch). "" when it is gone, else why git kept it."""
    try:
        git.delete_branch_at(repo, branch, oid)
    except SlotGitError as e:
        return e.tail.removeprefix("error: ")
    return ""


def delete_remote_at(git: Git, repo: str, ref: str, oid: str) -> str:
    """Delete origin's `ref` (refs/heads/...) only while it is at `oid`; the push is refused when the ref moved. "" or why it stayed."""
    try:
        git.delete_remote_at(repo, "origin", ref, oid)
    except SlotGitError as e:
        return e.tail
    return ""


def drop_branch(git: Git, repo: str, branch: str, tip: str) -> list[str]:
    """After a release: the worktrees on `branch` (never the main checkout) and then the local branch, but only while it is still at
    `tip`, the commit on_base was checked on. -> one line per thing that was kept, with why (empty: all gone). Nothing is forced, so a
    tree with changes keeps the branch too."""
    if branch in ("main", "master"):
        return []
    kept: list[str] = []
    for t in git.checkouts(repo):
        if t.branch == branch and not t.main:
            why = git.remove_worktree_why(repo, t.path)
            if why:
                kept.append(f"worktree {t.path} kept: {why}")
    if kept:
        return [*kept, f"branch {branch} kept: a worktree still has it"]
    if not tip_of(git, repo, branch):
        return []  # no local branch (a remote one was replayed)
    why = delete_branch_at(git, repo, branch, tip)  # a replayed branch is no ancestor; on_base was checked at `tip`, so only `tip` goes
    return [f"branch {branch} kept: {why}"] if why else []
