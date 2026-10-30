"""Leftovers of a branch that has landed: its worktrees and the branch itself. Plain `git worktree remove` only (it refuses a tree with
changes or untracked files, and a locked one), never --force; the branch goes only when patch for patch it is on origin/main."""
from dataclasses import dataclass
from pathlib import Path

from taskloop.app.release.shell import Shell

BASE = "origin/main"


@dataclass(frozen=True)
class Tree:
    path: Path
    branch: str  # "" when detached


def trees(repo: str | Path, sh: Shell) -> list[Tree]:
    """Every worktree of the repo (git worktree list), the main checkout first."""
    out = sh.run(["git", "worktree", "list", "--porcelain"], repo, check=False).stdout
    found: list[Tree] = []
    for block in out.split("\n\n"):
        fields: dict[str, str] = {}
        for ln in block.splitlines():
            key, _, val = ln.partition(" ")
            fields[key] = val
        if fields.get("worktree"):
            found.append(Tree(Path(fields["worktree"]), fields.get("branch", "").removeprefix("refs/heads/")))
    return found


def on_base(repo: str | Path, ref: str, sh: Shell, base: str = BASE) -> bool:
    """True when every commit of `ref` is on `base` by patch (git cherry: a branch replayed by a release is no ancestor but all `-`).
    False when git cannot say."""
    r = sh.run(["git", "cherry", base, ref], repo, check=False)
    return r.returncode == 0 and not any(ln.startswith("+") for ln in r.stdout.splitlines())


def remove_tree(repo: str | Path, path: Path, sh: Shell) -> str:
    """Remove one worktree; "" when it is gone, else why git kept it."""
    r = sh.run(["git", "worktree", "remove", str(path)], repo, check=False)
    return "" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["git worktree remove failed"])[-1]


def tip_of(repo: str | Path, branch: str, sh: Shell) -> str:
    """The oid a local branch is at now, "" when there is none."""
    return sh.run(["git", "rev-parse", "--verify", "-q", "refs/heads/" + branch], repo, check=False).stdout.strip()


def delete_branch_at(repo: str | Path, branch: str, oid: str, sh: Shell) -> str:
    """Delete a local branch only while it is still at `oid`, the commit that was checked (compare and delete: a commit added since
    keeps the branch). "" when it is gone, else why git kept it."""
    r = sh.run(["git", "update-ref", "-d", "refs/heads/" + branch, oid], repo, check=False)
    return "" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["git update-ref -d failed"])[-1].removeprefix("error: ")


def delete_remote_at(repo: str | Path, ref: str, oid: str, sh: Shell) -> str:
    """Delete origin's `ref` (refs/heads/...) only while it is at `oid`; the push is refused when the ref moved. "" or why it stayed."""
    r = sh.run(["git", "push", f"--force-with-lease={ref}:{oid}", "origin", ":" + ref], repo, check=False)
    return "" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["git push failed"])[-1]


def drop_branch(repo: str | Path, branch: str, tip: str, sh: Shell) -> list[str]:
    """After a release: the worktrees on `branch` (never the main checkout) and then the local branch, but only while it is still at
    `tip`, the commit on_base was checked on. -> one line per thing that was kept, with why (empty: all gone). Nothing is forced, so a
    tree with changes keeps the branch too."""
    if branch in ("main", "master"):
        return []
    main = trees(repo, sh)[:1]
    kept: list[str] = []
    for t in trees(repo, sh):
        if t.branch == branch and t not in main:
            why = remove_tree(repo, t.path, sh)
            if why:
                kept.append(f"worktree {t.path} kept: {why}")
    if kept:
        return [*kept, f"branch {branch} kept: a worktree still has it"]
    if not tip_of(repo, branch, sh):
        return []  # no local branch (a remote one was replayed)
    why = delete_branch_at(repo, branch, tip, sh)  # a replayed branch is no ancestor; on_base was checked at `tip`, so only `tip` goes
    return [f"branch {branch} kept: {why}"] if why else []
